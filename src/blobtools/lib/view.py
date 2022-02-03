#!/usr/bin/env python3

# pylint: disable=no-member, too-many-branches, too-many-locals, too-many-statements, broad-except

"""
Generate plots using BlobToolKit Viewer.

Usage:
  blobtools view [--format STRING...] [--host STRING] [--interactive]
  [--out PATH] [--param STRING...] [--ports RANGE] [--prefix STRING]
  [--preview STRING...] [--driver STRING] [--driver-log PATH]
  [--local] [--remote] [--timeout INT] [--view STRING...] DIRECTORY

Options:
      --format STRING         Image format (svg|png). [Default: png]
      --host STRING           Hostname. [Default: http://localhost]
      --interactive           Start interactive session (opens dataset in Firefox/Chromium). [Default: False]
      --out PATH              Directory for outfiles. [Default: .]
      --param key=value       Query string parameter.
      --ports RANGE           Port range for viewer and API. [Default: 8000-8099]
      --prefix STRING         URL prefix. [Default: view]
      --preview STRING        Field name.
      --driver STRING         Webdriver to use (chromium or firefox). [Default: firefox]
      --driver-log PATH       Path to driver logfile for debugging. [Default: /dev/null]
      --local                 Start viewer for local session. [Default: False]
      --remote                Start viewer for remote session. [Default: False]
      --timeout INT           Time to wait for page load in seconds. Default (0) is no timeout. [Default: 0]
      --view STRING           Plot type (blob|cumulative|snail). [Default: blob]
"""
import os
import shlex
import signal
import sys
import time
from pathlib import Path
from subprocess import PIPE
from subprocess import Popen

from docopt import docopt
from pyvirtualdisplay import Display
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from tqdm import tqdm

from .host import test_port
from .version import __version__


def file_ready(file_path):
    """Check if file is ready."""
    while not os.path.exists(file_path):
        # flush nfs cache by chowning parent to current owner
        parent = os.path.dirname(os.path.abspath(file_path))
        os.chown(parent, os.stat(parent).st_uid, os.stat(parent).st_gid)
        time.sleep(1)
        if os.path.isfile(file_path):
            return True
        raise ValueError("%s isn't a file!" % file_path)


def test_loc(args):
    """See if dataset needs to be hosted and, if so, find an empty port."""
    info = args["--host"].split(":")
    dataset = Path(args["DIRECTORY"]).name
    level = "dataset"
    if len(info) >= 2 and info[1] != "//localhost":
        loc = "%s/%s/%s/dataset/%s" % (
            args["--host"],
            args["--prefix"],
            dataset,
            dataset,
        )
        return loc, None, None, None, level
    if len(info) == 1 and info[0] != "localhost":
        # need to add test for http vs https
        loc = "http://%s/%s/%s/dataset/%s" % (
            args["--host"],
            args["--prefix"],
            dataset,
            dataset,
        )
        return loc, None, None, None, level
    if len(info) == 3:
        port = info[2]
        available = test_port(port, "test")
        if available:
            print("ERROR: No service running on port %s" % port)
            print("       Unable to connect to %s" % args["--host"])
            sys.exit(1)
        else:
            loc = "%s/%s/%s/dataset/%s" % (
                args["--host"],
                args["--prefix"],
                dataset,
                dataset,
            )
            return loc, None, None, None, level
    if args["DIRECTORY"] == "_":
        parent = "_"
        level = "blobdir"
    else:
        if not Path(args["DIRECTORY"]).exists():
            print(
                "ERROR: DIRECTORY '%s' must be a valid path to begin hosting."
                % args["DIRECTORY"]
            )
            sys.exit(1)
        dataset = Path(args["DIRECTORY"]).name
        if (
            Path("%s/meta.json" % args["DIRECTORY"]).is_file()
            or Path("%s/meta.json.gz" % args["DIRECTORY"]).is_file()
        ):
            parent = Path(args["DIRECTORY"]).resolve().absolute().parent
        else:
            level = "blobdir"
            parent = Path(args["DIRECTORY"]).resolve().absolute()
    port_range = args["--ports"].split("-")
    api_port = False
    port = False
    for i in range(int(port_range[0]), int(port_range[1])):
        if test_port(i, "test"):
            if not api_port:
                api_port = i
                continue
            if not port:
                port = i
            break
    # directory = Path(__file__).resolve().parent.parent
    cmd = "blobtools host --port %d --api-port %d %s" % (
        port,
        api_port,
        parent,
    )
    process = Popen(shlex.split(cmd), stdout=PIPE, stderr=PIPE, encoding="ascii")
    loc = "%s:%d/%s" % (args["--host"], port, args["--prefix"])
    if level == "dataset":
        loc += "/%s/dataset/%s" % (dataset, dataset)
    else:
        loc += "/all"
    for i in tqdm(
        range(0, 10),
        unit="s",
        ncols=75,
        desc="Initializing viewer",
        bar_format="{desc}",
    ):
        poll = process.poll()
        if poll is None:
            if test_port(port, "test"):
                break
            time.sleep(1)
        else:
            print(process.stdout.read(), file=sys.stderr)
            print(process.stderr.read(), file=sys.stderr)
            print("ERROR: Viewer quit unexpectedly", file=sys.stderr)
            print("Unable to run: %s" % cmd, file=sys.stderr)
            sys.exit(1)
    return loc, process, port, api_port, level


def firefox_driver(args):
    """Start firefox."""
    import geckodriver_autoinstaller

    geckodriver_autoinstaller.install()

    outdir = os.path.abspath(args["--out"])
    os.makedirs(Path(outdir), exist_ok=True)

    profile = webdriver.FirefoxProfile()
    profile.set_preference("browser.download.folderList", 2)
    profile.set_preference("browser.download.manager.showWhenStarting", False)
    profile.set_preference("browser.download.dir", outdir)
    profile.set_preference("browser.download.lastDir", args["--out"])
    profile.set_preference(
        "browser.helperApps.neverAsk.saveToDisk",
        "image/png, image/svg+xml, text/csv, text/plain, application/json",
    )

    options = Options()
    options.headless = not args["--interactive"]
    display = Display(visible=0, size=(800, 600))
    display.start()
    driver = webdriver.Firefox(
        options=options,
        firefox_profile=profile,
        service_log_path=args["--driver-log"],
    )
    time.sleep(2)
    return driver, display


def chromium_driver(args):
    """Start chromium browser."""
    import chromedriver_binary

    outdir = os.path.abspath(args["--out"])
    os.makedirs(Path(outdir), exist_ok=True)

    options = webdriver.ChromeOptions()
    if not args["--interactive"]:
        options.add_argument("headless")
    prefs = {}
    prefs["profile.default_content_settings.popups"] = 0
    prefs["download.default_directory"] = outdir
    options.add_experimental_option("prefs", prefs)
    display = Display(visible=0, size=(800, 600))
    display.start()
    driver = webdriver.Chrome(
        options=options,
        # executable_path=add option to set binary location,
        service_log_path=args["--driver-log"],
    )
    time.sleep(2)
    return driver, display


def static_view(args, loc, viewer):
    """Generate static images."""
    qstr = "staticThreshold=Infinity"
    qstr += "&nohitThreshold=Infinity"
    qstr += "&plotGraphics=svg"
    if args["--format"] == "svg":
        qstr += "&svgThreshold=Infinity"
    shape = "circle"
    for param in args["--param"]:
        qstr += "&%s" % str(param)
        key, value = param.split("=")
        if key == "plotShape":
            shape = value

    timeout = int(args["--timeout"])
    outdir = os.path.abspath(args["--out"])
    driver = None

    def handle_error(err):
        """Release resources before quitting."""
        if viewer is not None:
            viewer.send_signal(signal.SIGINT)
        if driver is not None:
            driver.quit()
            display.stop()
        print(err)
        sys.exit(1)

    if args["--driver"] == "firefox":
        """View dataset in Firefox."""
        driver, display = firefox_driver(args)
    elif args["--driver"] == "chromium":
        """View dataset in Chromium browser."""
        driver, display = chromium_driver(args)
    else:
        handle_error("%s is not a valid driver" % args["--driver"])

    try:
        view = args["--view"][0]
        if args["--preview"]:
            qstr += "#Filters"
        url = "%s/%s?%s" % (loc, view, qstr)
        print("Loading %s" % url)
        try:
            driver.get(url)
        except Exception as err:
            handle_error(err)

        for next_view in args["--view"]:
            if next_view != view:
                view = next_view
                url = "%s/%s?%s" % (loc, view, qstr)
                print("Navigating to %s" % url)
                try:
                    driver.get(url)
                except Exception as err:
                    handle_error(err)
            for fmt in args["--format"]:
                file = "%s.%s" % (Path(args["DIRECTORY"]).name, view)
                if view == "blob":
                    file += ".%s" % shape
                elif view == "busco":
                    view = "all_%s" % view
                    if fmt not in ("csv", "json"):
                        fmt = "json"
                file += ".%s" % fmt
                print("Fetching %s" % file)
                el_id = "%s_save_%s" % (view, fmt)
                print("waiting for element %s" % el_id)
                unstable = True
                start_time = time.time()
                while unstable:
                    elapsed_time = time.time() - start_time
                    if timeout and elapsed_time > timeout:
                        handle_error("Timeout waiting for file")
                    try:
                        element = WebDriverWait(driver, timeout).until(
                            EC.visibility_of_element_located((By.ID, el_id))
                        )
                        element.click()
                        unstable = False
                        file_name = "%s/%s" % (outdir, file)
                        print("waiting for file '%s'" % file_name)
                        file_ready(file_name)
                    except Exception as err:
                        time.sleep(1)

        for preview in args["--preview"]:
            print("Creating %s preview" % preview)
            for fmt in args["--format"]:
                el_id = "%s_preview_save_%s" % (preview, fmt)
                file = "%s.%s.preview.%s" % (Path(args["DIRECTORY"]).name, preview, fmt)
                try:
                    element = WebDriverWait(driver, timeout).until(
                        EC.visibility_of_element_located((By.ID, el_id))
                    )
                    element.click()
                    file_name = "%s/%s" % (outdir, file)
                    print("waiting for file '%s'" % file_name)
                    file_ready(file_name)
                except Exception as err:
                    handle_error(err)
        if viewer is not None:
            viewer.send_signal(signal.SIGINT)
        driver.quit()
        display.stop()
    except Exception as err:
        handle_error(err)
        # print(err)
        # if viewer is not None:
        #     viewer.send_signal(signal.SIGINT)
        # driver.quit()
        # display.stop()
    return True


def interactive_view(args, loc, viewer, level):
    if args["--driver"] == "firefox":
        """View dataset in Firefox."""
        driver, display = firefox_driver(args)
    elif args["--driver"] == "chromium":
        """View dataset in Chromium browser."""
        driver, display = chromium_driver(args)
    qstr = ""
    for param in args["--param"]:
        qstr += "&%s" % str(param)
    try:
        view = args["--view"][0]
        if args["--preview"]:
            qstr += "#Filters"
        if level == "dataset":
            url = "%s/%s" % (loc, view)
            if qstr:
                url += "?%s" % qstr
        else:
            url = loc if loc.endswith("all") else "%s/all" % loc
        print("Loading %s" % url)
        try:
            driver.get(url)
        except Exception as err:
            print(err)
        poll = viewer.poll()
        while poll is None:
            time.sleep(5)
            poll = viewer.poll()
        driver.quit()
        display.stop()
        if viewer is not None:
            viewer.send_signal(signal.SIGINT)
    except Exception as err:
        print(err)
        driver.quit()
        display.stop()
        if viewer is not None:
            viewer.send_signal(signal.SIGINT)
    return True


def remote_view(args, loc, viewer, port, api_port, level, remote):
    """View dataset remotely."""
    qstr = ""
    for param in args["--param"]:
        qstr += "&%s" % str(param)
    try:
        view = args["--view"][0]
        if args["--preview"]:
            qstr += "#Filters"
        if level == "dataset":
            url = "%s/%s" % (loc, view)
            if qstr:
                url += "?%s" % qstr
            print("View dataset at %s" % url)
        else:
            print("View datasets at %s" % loc)
        if remote:
            print("For remote access use:")
            print(
                "    ssh -L %d:127.0.0.1:%d -L %d:127.0.0.1:%d username@remote_host"
                % (port, port, api_port, api_port)
            )
        while True:
            time.sleep(5)
        if viewer is not None:
            viewer.send_signal(signal.SIGINT)
    except Exception as err:
        print("remote exception")
        print(err)
        if viewer is not None:
            viewer.send_signal(signal.SIGINT)
    return True


def main(args):
    """Entrypoint for blobtools view."""
    loc, viewer, port, api_port, level = test_loc(args)
    try:
        if args["--interactive"]:
            interactive_view(args, loc, viewer, level)
        elif args["--remote"]:
            remote_view(args, loc, viewer, port, api_port, level, True)
        elif args["--local"]:
            remote_view(args, loc, viewer, port, api_port, level, False)
        else:
            static_view(args, loc, viewer)
    except KeyboardInterrupt:
        pass
    finally:
        time.sleep(1)
        if viewer is not None:
            viewer.send_signal(signal.SIGINT)
        time.sleep(1)


def cli():
    """Entry point."""
    if len(sys.argv) == sys.argv.index(__name__.split(".")[-1]) + 1:
        args = docopt(__doc__, argv=[])
    else:
        args = docopt(__doc__, version=__version__)
    if not os.path.exists(os.environ["HOME"]):
        os.mkdir(os.environ["HOME"])
    main(args)


if __name__ == "__main__":
    cli()
