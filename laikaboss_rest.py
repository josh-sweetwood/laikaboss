#!/usr/bin/env python

from __future__ import print_function

from flask import Flask, json, request

from laikaboss import config
from laikaboss.constants import level_minimal, level_metadata, level_full
from laikaboss.objectmodel import ScanResult, ScanObject, QuitScanException, ExternalObject, ExternalVars
from laikaboss.dispatch import Dispatch, close_modules
from laikaboss.clientLib import getJSON
from laikaboss.util import init_logging
from interruptingcow import timeout
import traceback
import time
import sys

# Monkey patch the python syslog library to print all logging to STDOUT / STDERR,
# for Docker container standards compliance
import monkey_syslog


api = Flask(__name__)

@api.route('/scan', methods=['POST'])
def post_scan():
    filename = request.args.get('filename')
    ephID = request.args.get('ephID')
    uniqID = request.args.get('uniqID')
    contentType = request.args.get('contentType')
    timestamp = request.args.get('timestamp')
    source = request.args.get('source')
    origRootUID = request.args.get('origRootUID')
    extMetaData = request.args.get('extMetaData')
    level = int(request.args.get('level'))
    data = request.get_data()
    print("filename = {}".format(filename))
    print("ephID = {}".format(ephID))
    print("uniqID = {}".format(uniqID))
    print("contentType = {}".format(contentType))
    print("timestamp = {}".format(timestamp))
    print("source = {}".format(source))
    print("origRootUID = {}".format(origRootUID))
    print("extMetaData = {}".format(extMetaData))
    print("level = {}".format(level))
    print("data length = {}".format(len(data)))
    sys.stdout.flush()

    externalVars = ExternalVars(filename=filename,
                                ephID=ephID,
                                uniqID=uniqID,
                                contentType=contentType,
                                timestamp=timestamp,
                                source=source,
                                origRootUID=origRootUID,
                                extMetaData=extMetaData)

    externalObject = ExternalObject(buffer=data,
                                    level=level,
                                    externalVars=externalVars)

    result = ScanResult(
        source=externalObject.externalVars.source,
        level=externalObject.level)
    result.startTime = time.time()
    try:
        Dispatch(externalObject.buffer, result, 0,
            externalVars=externalObject.externalVars)
    except QuitScanException:
        raise
    except:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print(
            "exception on file: %s, detailed exception: %s" % (
            externalObject.externalVars.filename,
            repr(traceback.format_exception(exc_type, exc_value, exc_traceback))))
        sys.stdout.flush()
    result = getJSON(result, level=level)
    sys.stdout.flush()

    return result, 201

def main():
    # TODO: Add options?
    config_location = '/etc/laikaboss/laikaboss.conf'
    print("using config {}".format(config_location))
    sys.stdout.flush()
    config.init(path=config_location)
    init_logging()
    api.run(host='0.0.0.0', port=80, threaded=False)
    try:
        with timeout(30, exception=QuitScanException):
            close_modules()
    except QuitScanException:
        print("Caught scan termination exception during destruction")

if __name__ == '__main__':
    main()
