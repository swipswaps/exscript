# Copyright (C) 2007-2010 Samuel Abels.
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
import os, base64, re
from sqlalchemy    import create_engine
from Order         import Order
from OrderDB       import OrderDB
from lxml          import etree
from Exscript      import Account, Queue
from RestDaemon    import RestDaemon
from PythonService import PythonService
from util          import resolve_variables

class Config(object):
    def __init__(self, cfg_dir):
        self.cfg_dir   = cfg_dir
        filename       = os.path.join(cfg_dir, 'main.xml')
        self.cfgtree   = etree.parse(filename)
        self.variables = {}
        self.queues    = {}
        self._clean_tree()

    def _resolve(self, text):
        if text is None:
            return None
        return resolve_variables(self.variables, text.strip())

    def _clean_tree(self):
        # Read all variables.
        variables = self.cfgtree.find('variables') or []
        for element in variables:
            varname = element.tag.strip()
            value   = resolve_variables(self.variables, element.text)
            self.variables[varname] = value

        # Resolve variables everywhere.
        for element in self.cfgtree.iter():
            element.text = self._resolve(element.text)
            for attr in element.attrib:
                value                = element.attrib[attr]
                element.attrib[attr] = self._resolve(value)

    def init_account_pool_from_name(self, name):
        accounts = []
        element  = self.cfgtree.find('account-pool[@name="%s"]' % name)
        for child in element.iterfind('account'):
            user     = child.find('user').text
            password = child.find('password').text
            accounts.append(Account(user, base64.decodestring(password)))
        return accounts

    def init_queue_from_name(self, name, logdir):
        if self.queues.has_key(name):
            return self.queues[name]

        # Create the queue first.
        element     = self.cfgtree.find('queue[@name="%s"]' % name)
        max_threads = element.find('max-threads').text
        delete_logs = element.find('delete-logs') is not None
        queue       = Queue(verbose     = 0,
                            max_threads = max_threads,
                            logdir      = logdir,
                            delete_logs = delete_logs)

        # Add some accounts, if any.
        account_pool = element.find('account-pool')
        if account_pool is not None:
            accounts = self.init_account_pool_from_name(account_pool.text)
            queue.add_account(accounts)

        self.queues[name] = queue
        return queue

    def init_database_from_name(self, name):
        element = self.cfgtree.find('database[@name="%s"]' % name)
        dbn     = element.find('dbn').text
        print 'Creating database connection for', dbn
        engine  = create_engine(dbn)
        db      = OrderDB(engine)
        print 'Initializing database tables...'
        db.install()
        return db

    def init_service_from_name(self,
                               daemon,
                               name,
                               dirname,
                               queue = None):
        print 'Loading service "%s"...' % name,
        cfgfile    = os.path.join(dirname, 'service.xml')
        servicedir = os.path.join(self.cfg_dir, 'services', name)
        cfgtree    = etree.parse(cfgfile)
        element    = cfgtree.find('service')
        type       = element.get('type')

        if type == 'python':
            basename = element.get('filename')
            filename = os.path.join(dirname, basename)
            service  = PythonService(daemon,
                                     name,
                                     filename,
                                     servicedir,
                                     queue = queue)
        else:
            raise Exception('Invalid service type: %s' % type)
        print 'done.'
        return service

    def load_services(self, element, daemon):
        for service in element.iterfind('load-service'):
            name       = service.get('name')
            path       = service.get('path')
            queue_elem = service.find('queue')
            queue_name = queue_elem is not None and queue_elem.text
            logdir     = daemon.get_logdir()
            queue      = self.init_queue_from_name(queue_name, logdir)
            service    = self.init_service_from_name(daemon,
                                                     name,
                                                     path,
                                                     queue = queue)
            daemon.add_service(name, service)

    def init_rest_daemon(self, element):
        # Init the database for the daemon first, then
        # create the daemon (this does not start it).
        name    = element.get('name')
        address = element.find('address').text or ''
        port    = int(element.find('port').text)
        db_name = element.find('database').text
        logdir  = element.find('logdir').text
        db      = self.init_database_from_name(db_name)
        if not os.path.isdir(logdir):
            os.makedirs(logdir)
        daemon  = RestDaemon(name,
                             address,
                             port,
                             database = db,
                             logdir   = logdir)

        # Add some accounts, if any.
        account_pool = element.find('account-pool')
        for account in self.init_account_pool_from_name(account_pool.text):
            daemon.add_account(account)

        self.load_services(element, daemon)
        return daemon

    def init_daemon_from_name(self, name):
        # Create the daemon.
        element = self.cfgtree.find('daemon[@name="%s"]' % name)
        type    = element.get('type')
        if type == 'rest':
            return self.init_rest_daemon(element)
        else:
            raise Exception('No such daemon type: %s' % type)

    def init_daemons(self):
        daemons = []
        for element in self.cfgtree.iterfind('daemon'):
            name   = element.get('name')
            daemon = self.init_daemon_from_name(name)
            daemons.append(daemon)
        return daemons
