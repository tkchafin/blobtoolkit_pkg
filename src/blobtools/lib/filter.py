#!/usr/bin/env python3

# pylint: disable=no-member, too-many-branches, too-many-locals, too-many-statements, too-many-nested-blocks

"""
Filter a BlobDir.

Usage:
    blobtools filter [--param STRING...] [--query-string STRING] [--json JSON]
                     [--list TXT] [--invert] [--output DIRECTORY]
                     [--fasta FASTA] [--fastq FASTQ...] [--suffix STRING]
                     [--cov BAM] [--summary FILENAME] [--summary-rank RANK]
                     [--table FILENAME] [--table-fields STRING]
                     [--taxdump DIRECTORY] [--taxrule STRING] [--text TXT] [--text-header]
                     [--text-delimiter STRING] [--text-id-column INT] DIRECTORY

Arguments:
    DIRECTORY                   Existing BlobDir dataset directory.

Options:
    --param STRING            String of type param=value.
    --query-string STRING     List of param=value pairs from url query string.
    --json JSON               JSON format list file as generated by BlobtoolKit Viewer.
    --list TXT                Space or newline separated list of identifiers.
    --invert                  Invert filter (exclude matching records).
    --output DIRECTORY        Path to directory to generate a new, filtered BlobDir.
    --fasta FASTA             FASTA format assembly file to be filtered.
    --fastq FASTQ             FASTQ format read file to be filtered (requires --cov).
    --cov BAM                 BAM/SAM/CRAM read alignment file.
    --text TXT                generic text file to be filtered.
    --text-delimiter STRING   text file delimiter. [Default: whitespace]
    --text-id-column INT      index of column containing identifiers (1-based). [Default: 1]
    --text-header             Flag to indicate first row of text file contains field names. [Default: False]
    --suffix STRING           String to be added to filtered filename. [Default: filtered]
    --summary FILENAME        Generate a JSON-format summary of the filtered dataset.
    --summary-rank RANK       Taxonomic level for summary. [Default: phylum]
    --table FILENAME          Tabular output of filtered dataset.
    --table-fields STRING     Comma separated list of field IDs to include in the
                              table output. Use 'plot' to include all plot axes.
                              [Default: plot]
    --taxdump DIRECTORY       Location of NCBI new_taxdump directory.
    --taxrule STRING          Taxrule used when processing hits.
"""

import math
import re
import sys
import urllib
from collections import defaultdict

from docopt import docopt

from ..lib import busco
from ..lib import cov
from ..lib import fasta
from ..lib import file_io
from ..lib import hits
from ..lib import taxid
from ..lib import text

# from dataset import Metadata
from .fetch import fetch_field
from .fetch import fetch_metadata

# from taxdump import Taxdump
from .field import Category
from .field import Identifier
from .field import MultiArray
from .field import Variable
from .version import __version__

FIELDS = [
    {"flag": "--fasta", "module": fasta, "depends": ["identifiers"]},
    {
        "flag": "--fastq",
        "module": cov,
        "depends": ["identifiers"],
        "requires": ["--cov"],
    },
    {
        "flag": "--text",
        "module": text,
        "depends": ["identifiers"],
        "requires": ["--text-delimiter", "--text-header", "--text-id-column"],
    },
]

SUMMARY = [
    {"title": "taxonomy", "module": taxid, "depends": []},
    {
        "title": "baseComposition",
        "module": fasta,
        "depends": ["gc", "ncount", "length"],
    },
    {"title": "hits", "module": hits, "depends": ["length", "gc"]},
    {"title": "busco", "module": busco, "depends": []},
    {"title": "readMapping", "module": cov, "depends": ["length"]},
]


def parse_params(args, meta):
    """Parse and perform sanity checks on filer parameters."""
    strings = args.get("--param", [])
    valid = {
        "variable": ["Min", "Max", "Inv"],
        "category": ["Keys", "Inv"],
        "multiarray": ["Keys", "MinLength", "MaxLength", "Inv"],
    }
    if args.get("--query-string"):
        qstr = args["--query-string"]
        qstr = re.sub(r"^.*\?", "", qstr)
        qstr = re.sub(r"#.*$", "", qstr)
        strings += urllib.parse.unquote(qstr).split("&")
    params = defaultdict(dict)
    for string in strings:
        try:
            key, value = string.split("=")
        except ValueError:
            print("WARN: Skipping string '%s', not a valid parameter" % string)
            continue
        try:
            field_id, param = key.split("--")
        except ValueError:
            print("WARN: Skipping string '%s', not a valid parameter" % string)
            continue
        if meta.has_field(field_id):
            field_meta = meta.field_meta(field_id)
            # if field_meta.get('range'):
            #     field_type = 'variable'
            # else:
            #     field_type = 'category'
            if param in valid[field_meta["type"]]:
                params[field_id].update({param: value})
            else:
                print(
                    "WARN: '%s' is not a valid parameter for field '%s'"
                    % (param, field_id)
                )
        else:
            print("WARN: Skipping field '%s', not present in dataset" % field_id)
    return dict(params)


def filter_by_params(meta, directory, indices, params, invert_all):
    """Filter included set using params."""
    all_indices = indices[0:]
    for field_id, filters in params.items():
        field = fetch_field(directory, field_id, meta)
        invert = False
        if filters.get("Inv"):
            invert = True
        if isinstance(field, Category):
            keys = field.keys
            if filters.get("Keys"):
                keys = [
                    int(x) if x.isdigit() else field.keys.index(x)
                    for x in filters["Keys"].split(",")
                ]
                if not invert:
                    keys = [i for i, x in enumerate(field.keys) if i not in keys]
                keys = set(keys)
                indices = [i for i in indices if field.values[i] in keys]
        elif isinstance(field, Variable):
            low = -math.inf
            high = math.inf
            if filters.get("Min"):
                low = float(filters["Min"])
            if filters.get("Max"):
                high = float(filters["Max"])
            if invert:
                indices = [
                    i
                    for i in indices
                    if field.values[i] < low or field.values[i] > high
                ]
            else:
                indices = [i for i in indices if low <= field.values[i] <= high]
        elif isinstance(field, MultiArray):
            low = -math.inf
            high = math.inf
            length = False
            if filters.get("MinLength"):
                low = int(filters["MinLength"])
                length = True
            if filters.get("MaxLength"):
                high = int(filters["MaxLength"])
                length = True
            if length:
                if invert:
                    indices = [
                        i
                        for i in indices
                        if len(field.values[i]) < low or len(field.values[i]) > high
                    ]
                else:
                    indices = [
                        i for i in indices if low <= len(field.values[i]) <= high
                    ]
            if filters.get("Keys"):
                keys = [
                    int(x) if x.isdigit() else field.keys.index(x)
                    for x in filters["Keys"].split(",")
                ]
                cat_i = int(field.category_slot)
                if not invert:
                    keys = [i for i, x in enumerate(field.keys) if i not in keys]
                keys = set(keys)
                new_indices = []
                for i in indices:
                    for j in field.values[i]:
                        if j[cat_i] in keys:
                            new_indices.append(i)
                            break
                indices = new_indices
    if invert_all:
        inverted = [i for i in all_indices if i not in indices]
        return inverted
    return indices


def filter_by_json(identifiers, indices, json_file, invert):
    """Filter included set using json file."""
    data = file_io.load_yaml(json_file)
    id_set = set(data["identifiers"])
    if not invert:
        indices = [i for i in indices if identifiers[i] in id_set]
    else:
        indices = [i for i in indices if identifiers[i] not in id_set]
    return indices


def create_filtered_dataset(dataset_meta, indir, outdir, indices):
    """Write filtered records to new dataset."""
    meta = dataset_meta.to_dict()
    meta.update(
        {"fields": [], "origin": dataset_meta.dataset_id, "records": len(indices)}
    )
    meta.pop("id")
    meta = fetch_metadata(outdir, meta=meta)
    # meta = fetch_metadata(outdir, **args)
    for field_id in dataset_meta.list_fields():
        field_meta = dataset_meta.field_meta(field_id)
        if not field_meta.get("children"):
            field_meta.pop("data", False)
            keys = None
            slot = None
            headers = None
            full_field = fetch_field(indir, field_id, dataset_meta)
            if isinstance(full_field, (Variable, Identifier)):
                values = [full_field.values[i] for i in indices]
                if isinstance(full_field, Variable):
                    field_meta.update({"range": [min(values), max(values)]})
                    if field_id == "length":
                        meta.assembly.update({"span": sum(values)})
                        meta.assembly.update({"scaffold-count": len(values)})
            elif isinstance(full_field, Category):
                full_values = full_field.expand_values()
                values = [full_values[i] for i in indices]
            else:
                full_values = full_field.expand_values()
                values = [full_values[i] for i in indices]
                slot = full_field.category_slot
                try:
                    headers = full_field.headers
                except AttributeError:
                    pass
                if field_meta.get("parent"):
                    parent_field = fetch_field(
                        outdir, field_meta["parent"], dataset_meta
                    )
                    if parent_field:
                        keys = parent_field.keys
            field = type(full_field)(
                field_id,
                meta=field_meta,
                values=values,
                fixed_keys=keys,
                category_slot=slot,
                headers=headers,
            )
            parents = dataset_meta.field_parent_list(field_id)
            meta.add_field(parents, **field_meta, field_id=field_id)
            json_file = "%s/%s.json" % (outdir, field.field_id)
            file_io.write_file(json_file, field.values_to_dict())
    file_io.write_file("%s/meta.json" % outdir, meta.to_dict())


def main(args):
    """Entrypoint for blobtools filter."""
    meta = fetch_metadata(args["DIRECTORY"], **args)
    params = parse_params(args, meta)
    identifiers = fetch_field(args["DIRECTORY"], "identifiers", meta)
    indices = [index for index, value in enumerate(identifiers.values)]
    invert = args["--invert"]
    if params:
        indices = filter_by_params(meta, args["DIRECTORY"], indices, params, invert)
    if args["--json"]:
        indices = filter_by_json(identifiers.values, indices, args["--json"], invert)
    if args["--output"]:
        create_filtered_dataset(meta, args["DIRECTORY"], args["--output"], indices)
    ids = [identifiers.values[i] for i in indices]
    for field in FIELDS:
        if args[field["flag"]]:
            requirements = True
            if field.get("requires"):
                for flag in field["requires"]:
                    if flag not in args:
                        print(
                            "WARN: '%s' must be set to use option '%s'"
                            % (flag, field["flag"])
                        )
                        requirements = False
            if not requirements:
                continue
            field["module"].apply_filter(ids, args[field["flag"]], **args)
    if args["--table"]:
        full_field_ids = args["--table-fields"].split(",")
        expanded_ids = ["index", "identifiers"]
        field_ids = []
        alt_ids = {field_id: field_id for field_id in expanded_ids}
        for full_id in full_field_ids:
            try:
                field_id, alt_id = full_id.split("=")
                field_ids.append(field_id)
                alt_ids[field_id] = alt_id
            except ValueError:
                field_ids.append(full_id)
                alt_ids[full_id] = full_id
        fields = {"identifiers": fetch_field(args["DIRECTORY"], "identifiers", meta)}
        for field_id in field_ids:
            if field_id == "plot":
                for axis in ["x", "z", "y", "cat"]:
                    if axis in meta.plot:
                        expanded_ids.append(meta.plot[axis])
                        alt_ids.update({meta.plot[axis]: meta.plot[axis]})
                        fields[meta.plot[axis]] = fetch_field(
                            args["DIRECTORY"], meta.plot[axis], meta
                        )
            else:
                expanded_ids.append(field_id)
                alt_ids.update({field_id: field_id})
                fields[field_id] = fetch_field(args["DIRECTORY"], field_id, meta)
        table = [[alt_ids[field_id] for field_id in expanded_ids]]
        for i in indices:
            record = []
            for field_id in expanded_ids:
                if field_id == "index":
                    record.append(i)
                else:
                    value = fields[field_id].values[i]
                    if fields[field_id].keys:
                        value = fields[field_id].keys[value]
                    record.append(value)
            table.append(record)
        file_io.write_file(args["--table"], table)
    if args["--summary"]:
        summary_stats = {}
        for section in SUMMARY:
            requirements = True
            if section.get("requires"):
                for flag in section["requires"]:
                    if not args[flag]:
                        print(
                            "WARN: '%s' must be set to generate '%s' summary"
                            % (flag, section["title"])
                        )
                        requirements = False
            if not requirements:
                continue
            fields = {}
            if section.get("depends"):
                for field in section["depends"]:
                    fields.update({field: fetch_field(args["DIRECTORY"], field, meta)})
            if section["title"] == "hits":
                taxrule = args.get("--taxrule", None)
                if taxrule is None:
                    taxrule = meta.plot.get("cat", None)
                    if taxrule is not None:
                        taxrule = re.sub(r"_[^_]+$", "", taxrule)
                        args["--taxrule"] = taxrule
                    else:
                        continue
                field = "%s_%s" % (taxrule, args["--summary-rank"])
                fields.update({"hits": fetch_field(args["DIRECTORY"], field, meta)})
                if "y" in meta.plot:
                    fields.update(
                        {"cov": fetch_field(args["DIRECTORY"], meta.plot["y"], meta)}
                    )
            if section["title"] == "busco":
                lineages = []
                for field in meta.list_fields():
                    if field.endswith("_busco"):
                        lineages.append(field)
                        fields.update(
                            {field: fetch_field(args["DIRECTORY"], field, meta)}
                        )
                fields.update({"lineages": lineages})
            if section["title"] == "readMapping":
                libraries = []
                for field in meta.list_fields():
                    if field.endswith("_cov") and not field.endswith("_read_cov"):
                        library = field.replace("_cov", "")
                        libraries.append(library)
                        fields.update(
                            {field: fetch_field(args["DIRECTORY"], field, meta)}
                        )
                fields.update({"libraries": libraries})
            summary_stats.update(
                {
                    section["title"]: section["module"].summarise(
                        indices, fields, **args, meta=meta, stats=summary_stats
                    )
                }
            )
        stats = {}
        if "hits" in summary_stats:
            nohit_span = 0
            span = summary_stats["hits"]["total"]["span"]
            if "no-hit" in summary_stats["hits"]:
                nohit_span = summary_stats["hits"]["no-hit"]["span"]
                stats.update({"noHit": float("%.3f" % (nohit_span / span))})
            else:
                stats.update({"noHit": 0})
            if "taxonomy" in summary_stats and "target" in summary_stats["taxonomy"]:
                if summary_stats["taxonomy"]["target"] in summary_stats["hits"]:
                    target_span = summary_stats["hits"][
                        summary_stats["taxonomy"]["target"]
                    ]["span"]
                    stats.update(
                        {"target": float("%.3f" % (target_span / (span - nohit_span)))}
                    )
                elif "target" in summary_stats["hits"]:
                    target_span = summary_stats["hits"]["target"]["span"]
                    stats.update(
                        {"target": float("%.3f" % (target_span / (span - nohit_span)))}
                    )
                    del summary_stats["hits"]["target"]
                else:
                    stats.update({"target": 0})
            ratio = (
                summary_stats["hits"]["total"]["span"]
                / summary_stats["hits"]["total"]["n50"]
            )
            if ratio >= 100:
                ratio = int(float("%.3g" % ratio))
            else:
                ratio = float("%.3g" % ratio)
            stats.update({"spanOverN50": ratio})
        summary_stats.update({"stats": stats})
        file_io.write_file(args["--summary"], {"summaryStats": summary_stats})


def cli():
    """Entry point."""
    if len(sys.argv) == sys.argv.index(__name__.split(".")[-1]) + 1:
        args = docopt(__doc__, argv=[])
    else:
        args = docopt(__doc__, version=__version__)
    main(args)


if __name__ == "__main__":
    cli()