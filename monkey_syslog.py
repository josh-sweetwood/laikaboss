#!/usr/bin/env python
# Author: Josh Sweetwood (@josh-sweetwood)
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

'''
monkey_syslog

Library that monkey-patches the Python syslog library and prints all
syslog output to STDOUT / STDERR.  This library should pretty much
behave like the Python syslog library does as far as calls to openlog(),
closelog(), setlogmask(), and obviously the syslog() function itself.
'''

from __future__ import print_function
import sys
import os
import syslog

# Monkey patch the syslog library to send all logging to STDOUT
_default_syslog_priority_level = syslog.LOG_INFO
_default_syslog_facility = syslog.LOG_USER
_default_syslog_log_option = 0
_default_syslog_ident = os.path.basename(sys.argv[0][:-3] if sys.argv[0].endswith('.py') else sys.argv[0])
_default_syslog_maskpri = syslog.LOG_UPTO(syslog.LOG_DEBUG)

current_syslog_facility = _default_syslog_facility
current_syslog_logoption = _default_syslog_log_option
current_syslog_ident = _default_syslog_ident
current_syslog_maskpri = _default_syslog_maskpri

_priority_level_mask = 0b00000111
_facility_mask = 0b11111000

syslog_priority_level = {syslog.LOG_EMERG: "LOG_EMERG",
                         syslog.LOG_ALERT: "LOG_ALERT",
                         syslog.LOG_CRIT: "LOG_CRIT",
                         syslog.LOG_ERR: "LOG_ERR",
                         syslog.LOG_WARNING: "LOG_WARNING",
                         syslog.LOG_NOTICE: "LOG_NOTICE",
                         syslog.LOG_INFO: "LOG_INFO",
                         syslog.LOG_DEBUG: "LOG_DEBUG"}

syslog_facility = {syslog.LOG_KERN: "LOG_KERN",
                   syslog.LOG_USER: "LOG_USER",
                   syslog.LOG_MAIL: "LOG_MAIL",
                   syslog.LOG_DAEMON: "LOG_DAEMON",
                   syslog.LOG_AUTH: "LOG_AUTH",
                   syslog.LOG_LPR: "LOG_LPR",
                   syslog.LOG_NEWS: "LOG_NEWS",
                   syslog.LOG_UUCP: "LOG_UUCP",
                   syslog.LOG_CRON: "LOG_CRON",
                   syslog.LOG_SYSLOG: "LOG_SYSLOG",
                   syslog.LOG_LOCAL0: "LOG_LOCAL0",
                   syslog.LOG_LOCAL1: "LOG_LOCAL1",
                   syslog.LOG_LOCAL2: "LOG_LOCAL2",
                   syslog.LOG_LOCAL3: "LOG_LOCAL3",
                   syslog.LOG_LOCAL4: "LOG_LOCAL4",
                   syslog.LOG_LOCAL5: "LOG_LOCAL5",
                   syslog.LOG_LOCAL6: "LOG_LOCAL6",
                   syslog.LOG_LOCAL7: "LOG_LOCAL7"}

syslog_option = {syslog.LOG_PID: "LOG_PID",
                 syslog.LOG_CONS: "LOG_CONS",
                 syslog.LOG_NDELAY: "LOG_NDELAY",
                 syslog.LOG_NOWAIT: "LOG_NOWAIT",
                 syslog.LOG_PERROR: "LOG_PERROR"}

def monkey_syslog_syslog(*args, **kwargs):
    global _default_syslog_priority_level
    global current_syslog_facility
    global current_syslog_logoption
    global _priority_level_mask
    global _facility_mask
    priority = _default_syslog_priority_level
    facility = current_syslog_facility
    message = ""
    pid = None

    if current_syslog_logoption & syslog.LOG_PID:
        pid = os.getpid()

    if len(args) == 1:
        message = args[0]
    elif len(args) == 2:
        priority = args[0] & _priority_level_mask
        facility = args[0] & _facility_mask
        if facility == 0:
            facility = current_syslog_facility
        message = args[1]
    else:
        if len(kwargs) == 1:
            message = kwargs["message"]
        elif len(kwargs) == 2:
            priority = kwargs["priority"] | _priority_level_mask
            facility = kwargs["priority"] | _facility_mask
            if facility == 0:
                facility = current_syslog_facility
            message = kwargs["message"]

    if message:
        if (2**priority) & current_syslog_maskpri:
            formatted_msg = ""
            if pid:
                formatted_msg = 'ident={}|facility={}|priority_level={}|PID={}|message="{}"'.format(current_syslog_ident,
                                                                                                    syslog_facility[facility],
                                                                                                    syslog_priority_level[priority],
                                                                                                    pid,
                                                                                                    message)
            else:
                formatted_msg = 'ident={}|facility={}|priority_level={}|message="{}"'.format(current_syslog_ident,
                                                                                             syslog_facility[facility],
                                                                                             syslog_priority_level[priority],
                                                                                             message)
            if priority > syslog.LOG_ERR:
                print(formatted_msg)
            else:
                print(formatted_msg, file=sys.stderr)

def monkey_syslog_openlog(ident=_default_syslog_ident,
                          logoption=_default_syslog_log_option,
                          facility=_default_syslog_facility):
    global current_syslog_ident
    global current_syslog_logoption
    global current_syslog_facility    
    current_syslog_ident = ident
    current_syslog_logoption = logoption
    current_syslog_facility = facility

def monkey_syslog_setlogmask(maskpri):
    global current_syslog_maskpri
    prev = current_syslog_maskpri
    current_syslog_maskpri = maskpri
    return prev

def monkey_syslog_closelog():
    global current_syslog_facility
    global current_syslog_logoption
    global current_syslog_ident
    global _default_syslog_priority_level
    global _default_syslog_facility
    global _default_syslog_log_option
    global _default_syslog_ident
    current_syslog_facility = _default_syslog_facility
    current_syslog_logoption = _default_syslog_log_option
    current_syslog_ident = _default_syslog_ident

# Monkey patch!
syslog.syslog = monkey_syslog_syslog
syslog.openlog = monkey_syslog_openlog
syslog.setlogmask = monkey_syslog_setlogmask
syslog.closelog = monkey_syslog_closelog

def main():
    syslog.syslog("Defaults")
    syslog.openlog(ident="monkey", logoption=0, facility=syslog.LOG_LOCAL0)
    syslog.syslog("ident=monkey, logoption=0, facility=LOG_LOCAL0, priority_level=LOG_INFO")
    syslog.syslog(syslog.LOG_MAIL | syslog.LOG_ALERT, "ident=monkey, logoption=0, facility=LOG_MAIL, priority_level=LOG_ALERT")
    syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_NOTICE))
    syslog.syslog(syslog.LOG_WARNING, "ident=monkey, logoption=0, facility=LOG_LOCAL0, priority_level=LOG_WARNING")
    syslog.syslog("ident=monkey, logoption=0, facility=LOG_LOCAL0, priority_level=LOG_INFO") # shouldn't print
    syslog.syslog(syslog.LOG_CRON | syslog.LOG_NOTICE, "ident=monkey, logoption=0, facility=LOG_CRON, priority_level=LOG_NOTICE")
    syslog.syslog(syslog.LOG_INFO, "ident=monkey, logoption=0, facility=LOG_LOCAL0, priority_level=LOG_INFO") # shouldn't print
    syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))
    syslog.syslog(syslog.LOG_INFO, "ident=monkey, logoption=0, facility=LOG_LOCAL0, priority_level=LOG_INFO")
    syslog.syslog(syslog.LOG_UUCP | syslog.LOG_CRIT, "ident=monkey, logoption=0, facility=LOG_UUCP, priority_level=LOG_CRIT")
    syslog.closelog()
    syslog.syslog("Defaults")
    syslog.openlog(ident="newlog", logoption=syslog.LOG_PID, facility=syslog.LOG_DAEMON)
    syslog.syslog("ident=newlog, logoption=syslog.LOG_PID, facility=LOG_DAEMON, priority_level=LOG_INFO")
    syslog.closelog()
    syslog.syslog("Defaults again")

if __name__ == '__main__':
    main()
