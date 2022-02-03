#!/usr/bin/env python3

"""
BlobTools2 - assembly exploration, QC and filtering.

usage: blobtools [<command>] [<args>...] [-h|--help] [--version]

commands:
    add             add data to a BlobDir
    create          create a new BlobDir
    filter          filter a BlobDir
    host            host interactive view of all BlobDirs in a directory
    replace         call blobtools add with --replace flag
    remove          remove one or more fields from a BlobDir
    validate        validate a BlobDir
    view            generate plots using BlobToolKit Viewer
    -h, --help      show this
    -v, --version   show version number
See 'blobtools <command> --help' for more information on a specific command.

examples:
    # 1. Create a new BlobDir from a FASTA file:
    ./blobtools create --fasta examples/assembly.fasta BlobDir

    # 2. Create a new BlobDir from a BlobDB:
    ./blobtools create --blobdb examples/blobDB.json BlobDir

    # 3. Add Coverage data from a BAM file:
    ./blobtools add --cov examples/assembly.reads.bam BlobDir

    # 4. Assign taxonomy from BLAST hits:
    ./blobtools add add --hits examples/blast.out --taxdump ../taxdump BlobDir

    # 5. Add BUSCO results:
    ./blobtools add --busco examples/busco.tsv BlobDir

    # 6. Host an interactive viewer:
    ./blobtools host BlobDir

    # 7. Filter a BlobDir:
    ./blobtools filter --param length--Min=5000 --output BlobDir_len_gt_5000 BlobDir
"""


import sys

from docopt import DocoptExit
from docopt import docopt
from pkg_resources import working_set
from tolkein import tolog

from .lib.version import __version__

LOGGER = tolog.logger(__name__)


def cli():
    """Entry point."""
    if len(sys.argv) > 1:
        try:
            args = docopt(__doc__, help=False, version=__version__)
        except DocoptExit:
            args = {"<command>": sys.argv[1]}
        if args["<command>"]:
            # load <command> from entry_points
            for entry_point in working_set.iter_entry_points("blobtools.subcmd"):
                if entry_point.name == args["<command>"]:
                    subcommand = entry_point.load()
                    sys.exit(subcommand())
            LOGGER.error("'blobtools %s' is not a valid command", args["<command>"])
            sys.exit(1)
    print(__doc__)
    raise DocoptExit