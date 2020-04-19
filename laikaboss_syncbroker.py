#!/usr/bin/env python
# Heavily based on existing software from laikad.py in this same repository
# Copyright 2015 Lockheed Martin Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

'''
laikaboss_syncbroker

Command line program for running the broker process for the Laika framework.
'''

# Follows the Simple Pirate Pattern for ZMQ connections

from ConfigParser import ConfigParser
import functools
import logging
from optparse import OptionParser
import sys
import os
import signal
import syslog
import time
import json
import zmq
from laikaboss.objectmodel import ScanResult, ScanObject

# Monkey patch the python syslog library to print all logging to STDOUT / STDERR,
# for Docker container standards compliance
import monkey_syslog

SHUTDOWN_GRACE_TIMEOUT_DEFAULT = 30

# Status values for the state of a worker
LRU_READY = "\x01"          # Ready for work
LRU_RESULT_READY = "\x02"   # Here is the previous result, ready for more work
LRU_RESULT_QUIT = "\x03"    # Here is the previous result, I quit
LRU_QUIT = "\x04"           # I quit


# Class to serialize laikaboss objects to json
class ResultEncoder(json.JSONEncoder):
    '''ResultEncoder class'''
    def default(self, obj):
        if isinstance(obj, ScanObject):
            newdict = obj.__dict__.copy()
            del newdict['buffer']
            return newdict
        if isinstance(obj, ScanResult):
            res = {}
            res['rootUID'] = obj.rootUID
            res['source'] = obj.source
            res['level'] = obj.level
            res['startTime'] = obj.startTime
            tmp_files = {}
            for uid, sO in obj.files.iteritems():
                tmp_files[str(uid)] = sO
            res['files'] = tmp_files
            return res
        return json.JSONEncoder.default(self, obj)

# Variable to store configuration options from file
CONFIGS = {}

# Defaults for all available configurations
# To be used if not specified on command line or config file
DEFAULT_CONFIGS = {
    'brokerfrontend': 'tcp://*:5558',
    'brokerbackend': 'tcp://*:5559',
    'gracetimeout': '30',
    'laikaboss_syncbroker_dev_config_path' : 'etc/laikaboss/laikaboss_syncbroker.conf',
    'laikaboss_syncbroker_sys_config_path' : '/etc/laikaboss/laikaboss_syncbroker.conf'
    }

def log_debug(message):
    '''Log a debug message'''
    syslog.syslog(syslog.LOG_DEBUG, "DEBUG (%s) %s" % (os.getpid(), message))

def get_option(option, default=''):
    '''Get the value of an option from the configuration'''
    value = default
    if option in CONFIGS:
        value = CONFIGS[option]
    elif option in DEFAULT_CONFIGS:
        value = DEFAULT_CONFIGS[option]
    return value

def shutdown_handler(proc, signum, frame):
    '''
    Signal handler for shutting down the given process.

    Arguments:
    proc    --  The process that should be shutdown.

    '''
    logging.debug("Shutdown handler triggered (%d)", signum)
    proc.shutdown()


# Follows the Load Balancing Pattern for ZMQ connections
class SyncBroker(object):
    '''
    Broker class for receiving syncronous scan requests. The requests will be
    doled out to the worker processes. The results of the scan will be
    returned back to the client.
    '''

    def __init__(self, broker_backend_address, broker_frontend_address,
                 shutdown_grace_timeout=SHUTDOWN_GRACE_TIMEOUT_DEFAULT):
        '''Main constructor'''
        super(SyncBroker, self).__init__()
        self.broker_backend_address = broker_backend_address
        self.broker_frontend_address = broker_frontend_address
        self.shutdown_grace_timeout = shutdown_grace_timeout
        self.keep_running = True

    def shutdown(self):
        '''Shutdown method to be called by the signal handler'''
        logging.debug("Broker: shutdown handler triggered")
        self.keep_running = False

    def run(self):
        '''Main process logic'''
        logging.debug("Broker: starting up")
        self.keep_running = True

        # Add intercept for graceful shutdown
        signal.signal(signal.SIGTERM, functools.partial(shutdown_handler, self))
        signal.signal(signal.SIGINT, functools.partial(shutdown_handler, self))

        context = zmq.Context(1)

        # Connection for workers
        backend = context.socket(zmq.ROUTER)
        backend.bind(self.broker_backend_address)
        backend_poller = zmq.Poller()
        backend_poller.register(backend, zmq.POLLIN)

        # Connection for clients
        frontend = context.socket(zmq.ROUTER)
        frontend.bind(self.broker_frontend_address)
        frontend_poller = zmq.Poller()
        frontend_poller.register(frontend, zmq.POLLIN)
        frontend_poller.register(backend, zmq.POLLIN) # Also grab worker updates

        # Keep a list of the workers that have checked in as available for work
        available_workers = []
        # Keep a list of workers currently doing work, so that if we are asked
        # to shutdown, we can hang around long enough to forward the scan
        # results back to the requesting clients.
        working_workers = []

        while self.keep_running:
            logging.debug("Broker: beginning loop\n\tavailable: %s\n\tworking:"
                          " %s", str(available_workers), str(working_workers))

            try:
                if available_workers:
                    # Poll both clients and workers
                    msgs = dict(frontend_poller.poll(10000))
                else:
                    # Poll only workers
                    msgs = dict(backend_poller.poll(10000))

                # Check in with clients
                if msgs.get(frontend) == zmq.POLLIN:
                    # msg should be in the following format
                    # [client_id, '', request]
                    # where:
                    #   client_id   --  ZMQ identifier of the client socket
                    #   request     --  The content of the request to be sent to
                    #                   the worker
                    msg = frontend.recv_multipart()
                    worker_id = available_workers.pop(0)
                    # reply should be in the following format
                    # [worker_id, '', client_id, '', request]
                    # where:
                    #   worker_id   --  ZMQ identifier of the worker socket
                    #   client_id   --  ZMQ identifier of the client socket
                    #   request     --  The content of the request to be sent to
                    #                   the worker
                    backend.send_multipart([worker_id, ''] + msg)
                    working_workers.append(worker_id)

                # Check in with workers
                if msgs.get(backend) == zmq.POLLIN:
                    # msg should be in one of the following formats
                    # [worker_id, '', status]
                    # [worker_id, '', status, '', client_id, '', reply]
                    # where:
                    #   worker_id   --  ZMQ identifier of the worker socket
                    #   status      --  One of our defined status constants,
                    #                   determines how we handle this request
                    #   client_id   --  ZMQ identifier of the client socket
                    #   reply       --  The content of the reply
                    msg = backend.recv_multipart()
                    #logging.debug("Broker: received message %s", str(msg))
                    worker_id = msg[0]
                    status = msg[2]

                    if status == LRU_READY:
                        logging.debug("Broker: worker (%s) ready", worker_id)
                        if (worker_id not in available_workers and
                                worker_id not in working_workers):
                            available_workers.append(worker_id)
                    elif status == LRU_RESULT_READY:
                        logging.debug("Broker: worker (%s) finished scan, "
                                      "ready", worker_id)
                        try:
                            working_workers.remove(worker_id)
                        except ValueError:
                            pass
                        # reply should be in the following format
                        # [client_id, '', reply]
                        # where:
                        #   client_id   --  ZMQ identifier of the client socket
                        #   reply       --  The content of the reply
                        frontend.send_multipart(msg[4:])
                        if (worker_id not in available_workers and
                                worker_id not in working_workers):
                            available_workers.append(worker_id)
                    elif status == LRU_RESULT_QUIT:
                        logging.debug("Broker: worker (%s) finished scan, "
                                      "quitting", worker_id)
                        try:
                            working_workers.remove(worker_id)
                        except ValueError:
                            pass
                        # reply should be in the following format
                        # [client_id, '', reply]
                        # where:
                        #   client_id   --  ZMQ identifier of the client socket
                        #   reply       --  The content of the reply
                        frontend.send_multipart(msg[4:])
                    elif status == LRU_QUIT:
                        logging.debug("Broker: worker (%s) quitting", worker_id)
                        try:
                            available_workers.remove(worker_id)
                        except ValueError:
                            pass
                    else:
                        logging.debug("Broker: bad worker message received")
            except zmq.ZMQError as zmqerror:
                if "Interrupted system call" not in str(zmqerror):
                    logging.exception("Broker: Received ZMQError")
                else:
                    logging.debug("Broker: ZMQ interrupted by shutdown signal")

        # Begin graceful shutdown
        logging.debug("Broker: beginning graceful shutdown sequence")
        # Wait for a grace period to allow workers to finish working
        poll_timeout = (self.shutdown_grace_timeout / 3) * 1000 or 1
        start_time = time.time()
        while(working_workers and
              (time.time() - start_time < self.shutdown_grace_timeout)):
            logging.debug("Broker: beginning graceful shutdown loop\n\tworking:"
                          "%s", str(working_workers))
            msgs = dict(backend_poller.poll(poll_timeout))
            if msgs.get(backend) == zmq.POLLIN:
                # msg should be in one of the following formats
                # [worker_id, '', status]
                # [worker_id, '', status, '', client_id, '', reply]
                # where:
                #   worker_id   --  ZMQ identifier of the worker socket
                #   status      --  One of our defined status constants,
                #                   determines how we handle this request
                #   client_id   --  ZMQ identifier of the client socket
                #   reply       --  The content of the reply
                msg = backend.recv_multipart()
                worker_id = msg[0]
                status = msg[2]
                if status == LRU_RESULT_READY or status == LRU_RESULT_QUIT:
                    logging.debug("Broker: worker (%s) finished scan",
                                  worker_id)
                    try:
                        working_workers.remove(worker_id)
                    except ValueError:
                        pass
                    # reply should be in the following format
                    # [worker_id, '', client_id, '', request]
                    # where:
                    #   worker_id   --  ZMQ identifier of the worker socket
                    #   client_id   --  ZMQ identifier of the client socket
                    #   request     --  The content of the request to be sent to
                    #                   the worker
                    frontend.send_multipart(msg[4:])

        logging.debug("Broker: finished")

# Globals to share in the signal hander
KEEP_RUNNING = True

def main():
    '''Main program logic.'''
    parser = OptionParser(usage="usage: %prog [options]\n"
                          "Default settings in config file: laikaboss_syncbroker.conf")

    parser.add_option("-d", "--debug",
                      action="store_true", default=False,
                      dest="debug",
                      help="enable debug messages to the console.")
    parser.add_option("-c", "--laikaboss-syncbroker-config",
                      action="store", type="string",
                      dest="laikaboss_syncbroker_config_path",
                      help="specify a path for laikaboss_syncbroker configuration")
    parser.add_option("-b", "--broker-backend",
                      action="store", type="string",
                      dest="broker_backend_address",
                      help="specify an address for the workers to connect to. "
                      "ex: tcp://*:5559")
    parser.add_option("-f", "--broker-frontend",
                      action="store", type="string",
                      dest="broker_frontend_address",
                      help="specify an address for clients to connect to. ex: "
                      "tcp://*:5558")
    parser.add_option("-i", "--id",
                      action="store", type="string",
                      dest="runas_uid",
                      help="specify a valid username to switch to after starting "
                      "as root.")
    parser.add_option("-g", "--grace-timeout",
                      action="store", type="int",
                      dest="gracetimeout",
                      help="when shutting down, the timeout to allow workers to"
                      " finish ongoing scans before being killed")
    (options, _) = parser.parse_args()

    # Set the configuration file path for laikaboss_syncbroker.conf
    config_location = '/etc/laikaboss/laikaboss_syncbroker.conf'
    if options.laikaboss_syncbroker_config_path:
        config_location = options.laikaboss_syncbroker_config_path
        if not os.path.exists(options.laikaboss_syncbroker_config_path):
            print "the provided config path is not valid, exiting"
            return 1
    # Next, check to see if we're in the top level source directory (dev environment)
    elif os.path.exists(DEFAULT_CONFIGS['laikaboss_syncbroker_dev_config_path']):
        config_location = DEFAULT_CONFIGS['laikaboss_syncbroker_dev_config_path']
    # Next, check for an installed copy of the default configuration
    elif os.path.exists(DEFAULT_CONFIGS['laikaboss_syncbroker_sys_config_path']):
        config_location = DEFAULT_CONFIGS['laikaboss_syncbroker_sys_config_path']
    # Exit
    else:
        print 'A valid laikaboss_syncbroker configuration was not found in either of the following locations:\
\n%s\n%s' % (DEFAULT_CONFIGS['laikaboss_syncbroker_dev_config_path'], DEFAULT_CONFIGS['laikaboss_syncbroker_sys_config_path'])
        return 1

    # Read the laikaboss_syncbroker config file
    config_parser = ConfigParser()
    config_parser.read(config_location)

    # Parse through the config file and append each section to a single dict
    for section in config_parser.sections():
        CONFIGS.update(dict(config_parser.items(section)))

    if options.broker_backend_address:
        broker_backend_address = options.broker_backend_address
    else:
        broker_backend_address = get_option('brokerbackend')

    if options.broker_frontend_address:
        broker_frontend_address = options.broker_frontend_address
    else:
        broker_frontend_address = get_option('brokerfrontend')

    if options.gracetimeout:
        gracetimeout = options.gracetimeout
    else:
        gracetimeout = int(get_option('gracetimeout'))

    # Get the UserID to run as, if it was not specified on the command line
    # we'll use the current user by default
    runas_uid = None
    runas_gid = None

    if options.runas_uid:
        from pwd import getpwnam
        runas_uid = getpwnam(options.runas_uid).pw_uid
        runas_gid = getpwnam(options.runas_uid).pw_gid

    if options.debug:
        logging.basicConfig(level=logging.DEBUG)

    # Lower privileges if a UID has been set
    try:
        if runas_uid:
            os.setgid(runas_gid)
            os.setuid(runas_uid)
    except OSError:
        print "Unable to set user ID to %i, defaulting to current user" % runas_uid

    broker = SyncBroker(broker_backend_address, broker_frontend_address, gracetimeout)

    # Add intercept for graceful shutdown
    def shutdown(signum, frame):
        '''Signal handler for shutting down supervisor gracefully'''
        logging.debug("Main: shutdown handler triggered")
        global KEEP_RUNNING
        KEEP_RUNNING = False
        broker.shutdown()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Start the broker
    broker.run()

    logging.debug("Main: finished")
    return 0

if __name__ == '__main__':
    main()
