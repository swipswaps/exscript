# Copyright (C) 2007 Samuel Abels, http://debain.org
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2, as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
import os, re, exceptions, otp
import telnetlib
from Exception import TransportException
from Transport import Transport as Base, \
                      cisco_user_re,     \
                      junos_user_re,     \
                      unix_user_re,      \
                      pass_re,           \
                      skey_re,           \
                      huawei_re,         \
                      login_fail_re

True  = 1
False = 0

class Transport(Base):
    def __init__(self, *args, **kwargs):
        Base.__init__(self, **kwargs)
        self.tn     = None
        self.debug  = kwargs.get('debug', 0)


    def connect(self, hostname):
        assert self.tn is None
        self.tn = telnetlib.Telnet(hostname)
        self.tn.set_receive_callback(self._receive_cb)
        #self.tn.set_debuglevel(1)
        if self.tn is None:
            return False
        return True


    def authenticate(self, user, password):
        while 1:
            # Wait for the user prompt.
            #print 'Waiting for prompt'
            prompt  = [login_fail_re,
                       cisco_user_re,
                       junos_user_re,
                       unix_user_re,
                       skey_re,
                       pass_re,
                       huawei_re,
                       self.prompt_re]
            which   = None
            matches = None
            try:
                (which, matches, _) = self.tn.expect(prompt, self.timeout)
            except:
                print 'Telnet.authenticate(): Error while waiting for prompt'
                raise

            # No match.
            if which < 0:
                raise TransportException("Timeout while waiting for prompt")

            # Login error detected.
            elif which == 0:
                raise TransportException("Login failed")

            # User name prompt.
            elif which <= 3:
                #print "Username prompt received."
                if self.host_type == 'unknown':
                    self.host_type = ('cisco', 'junos', 'unix')[which - 1]
                self.send(user + '\r')
                continue

            # s/key prompt.
            elif which == 4:
                #print "S/Key prompt received."
                seq    = int(matches.group(1))
                seed   = matches.group(2)
                #print "Seq:", seq, "Seed:", seed
                phrase = otp.generate(password, seed, seq, 1, 'md4', 'sixword')[0]
                self.tn.expect([pass_re], self.timeout)
                self.send(phrase + '\r')
                #print "Password sent."
                continue
            
            # Cleartext password prompt.
            elif which == 5:
                #print "Cleartext prompt received."
                self.send(password + '\r')
                continue

            # Huawei welcome message.
            elif which == 6:
                self.host_type = 'huawei'

            # Shell prompt.
            elif which == 7:
                #print "Shell prompt received."
                # Switch to script compatible output (where supported).
                #print 'Host type:', self.host_type
                if self.host_type == 'cisco':
                    self.execute('term len 0')
                break

            else:
                assert 0 # Not reached.


    def authorize(self, password):
        # Make sure that the device supports AAA.
        if self.host_type != 'cisco':
            return

        self.send('enable\r')

        # The username should not be asked, so not passed.
        return self.authenticate('', password)


    def expect_prompt(self):
        # Wait for a prompt.
        self.response = None
        try:
            (result, _, self.response) = self.tn.expect([self.prompt_re],
                                                        self.timeout)
        except:
            print 'Error while waiting for a prompt'
            raise

        if result == -1 or self.response is None:
            error = 'Error while waiting for response from device'
            raise TransportException(error)

        # We skip the first line because it contains the echo of the command
        # sent.
        for line in self.response.split('\n')[1:]:
            match = self.error_re.match(line)
            if match is None:
                continue
            raise TransportException('Device said:\n' + self.response)


    def send(self, data):
        #print 'Sending "%s"' % data
        try:
            self.tn.write(data)
        except:
            print 'Error while writing to connection'
            raise


    def execute(self, data):
        # Send the command.
        self.send(data + '\r')
        return self.expect_prompt()


    def close(self):
        self.tn.close()