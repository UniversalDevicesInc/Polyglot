#! /usr/bin/python
""" Polyglot loader """

import argparse
import logging
import os
import shutil
import sys
import tempfile
import zipfile


def parse_arguments():
    """ Parse the command line arguments """
    default_config = os.path.join(os.path.dirname(__file__), '..', 'config')
    default_config = os.path.abspath(default_config)

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', dest='config_dir', type=str,
                        default=default_config,
                        help='Polyglot configuration directory')
    parser.add_argument('-v', '--verbose', dest='verbose', default=0,
                        action="store_const", const=1,
                        help="Enable verbose logging")
    parser.add_argument('-vv', dest='verbose', default=0,
                        action="store_const", const=2,
                        help="Enable very verbose logging")
    args = parser.parse_args()
    return args


def setup_config(config_dir):
    """ Setup configuration directory. """
    config_dir = os.path.abspath(config_dir)
    if not os.path.isdir(config_dir):
        try:
            os.mkdir(config_dir)
        except OSError as err:
            print('Polyglot could not create configuration directory.')
            print(repr(err))
            sys.exit(1)
    if not os.path.isdir(os.path.join(config_dir, 'node_servers')):
        try:
            os.mkdir(os.path.join(config_dir, 'node_servers'))
        except OSError as err:
            print('Polyglot could not create user node server directory.')
            print(repr(err))
            sys.exit(1)
    return config_dir


def setup_env():
    """ Setup Polyglot environment """
    if in_pyz():
        # Polyglot running from pyz file
        source_dir = extract_pyz()
    else:
        # Polyglot running from regular directory
        source_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..'))

    # add source directory to python path
    sys.path.insert(0, source_dir)

    return source_dir


def in_pyz():
    """ Determine if running in pyz archive """
    pyz_file = os.path.abspath(os.path.dirname(__file__))
    if zipfile.is_zipfile(pyz_file):
        return True
    else:
        return False


def extract_pyz():
    """ Extract PYZ contents to temp directory """
    pyz_file = os.path.abspath(os.path.dirname(__file__))
    source_dir = tempfile.mkdtemp(prefix='polyglot_')
    pyz_archive = zipfile.ZipFile(pyz_file, mode='r')
    pyz_archive.extractall(path=source_dir)
    pyz_archive.close()
    return source_dir


def setup_logging(config_dir, verbose):
    """ Setup the Polyglot logs """
    # pylint: disable=global-statement
    # create basic stdout log
    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    fmt = '%(levelname)-8s [%(asctime)s] %(name)s: %(message)s'
    dtfmt = '%m-%d-%Y %H:%M:%S'
    logging.basicConfig(level=level, format=fmt, datefmt=dtfmt)

    # create file log at {CONFIG}/polyglot.log
    log_path = os.path.join(config_dir, 'polyglot.log')
    file_handler = logging.FileHandler(log_path, mode='w', delay=True)
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt=dtfmt))
    logging.getLogger('').addHandler(file_handler)

    # special handling to suppress chatter from urllib3 and requests
    # when at "info" level logging.
    if verbose == 1:
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)

def cleanup(source_dir):
    """ Cleanup Polyglot environment """
    if in_pyz():
        shutil.rmtree(source_dir)


def main():
    """ Starts Polyglot Server """
    # read arguments
    # [future] PID File
    # [future] daemonize
    args = parse_arguments()

    # setup config directory
    config_dir = setup_config(args.config_dir)

    # create environment, add to Python Path
    source_dir = setup_env()

    # setup log
    setup_logging(config_dir, args.verbose)

    # setup polyglot
    from polyglot import nodeserver_helpers
    from polyglot.core import Polyglot
    nodeserver_helpers.SERVER_LIB_EXTERNAL = \
        os.path.join(config_dir, 'node_servers')

    # create polyglot
    pglot = Polyglot(config_dir)

    # setup and run polyglot
    pglot.setup()
    pglot.run()

    # cleanup and exit
    cleanup(source_dir)
    sys.exit(0)


if __name__ == "__main__":
    main()
