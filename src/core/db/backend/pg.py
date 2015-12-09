import os
import shutil
import re
import psycopg2
from psycopg2.extensions import AsIs

from config import settings

'''
DataHub internal APIs for postgres repo_base
'''
HOST = settings.DATABASES['default']['HOST']
PORT = 5432

if settings.DATABASES['default']['PORT'] != '':
    try:
        PORT = int(settings.DATABASES['default']['PORT'])
    except:
        pass


class PGBackend:

    def __init__(self, user, password, host=HOST, port=PORT, repo_base=None):
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.repo_base = repo_base

        self.__open_connection__()

    def __open_connection__(self):
        self.connection = psycopg2.connect(
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.repo_base)

        self.connection.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

    def reset_connection(self, repo_base):
        self.repo_base = repo_base
        self.__open_connection__()

    def close_connection(self):
        self.connection.close()

    def _check_for_injections(self, noun):
        ''' throws exceptions unless the noun contains only alphanumeric
            chars, hyphens, and underscores, and must not begin or end with
            a hyphen or underscore
        '''

        invalid_noun_msg = (
            "Usernames, repo names, and table names may only contain "
            "alphanumeric characters, hyphens, and underscores, and must not "
            "begin or end with an a hyphen or underscore."
        )

        regex = r'^(?![\-\_])[\w\-\_]+(?<![\-\_])$'
        valid_pattern = re.compile(regex)
        matches = valid_pattern.match(noun)

        if matches is None:
            raise ValueError(invalid_noun_msg)

    def create_repo(self, repo):
        ''' creates a postgres schema for the user.'''
        self._check_for_injections(repo)

        query = 'CREATE SCHEMA IF NOT EXISTS %s AUTHORIZATION %s'
        params = (AsIs(repo), AsIs(self.user))
        return self.execute_sql(query, params)

    def list_repos(self):
        query = ('SELECT schema_name AS repo_name '
                 'FROM information_schema.schemata '
                 'WHERE schema_owner = %s')

        params = (self.user,)
        return self.execute_sql(query, params)

    def delete_repo(self, repo, force=False):
        ''' deletes a repo and the folder the user's repo files are in. '''
        self._check_for_injections(repo)

        # delete the folder that repo files are in
        repo_dir = '/user_data/%s/%s' % (self.user, repo)
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)

        # drop the schema
        query = 'DROP SCHEMA %s %s'
        params = (AsIs(repo), AsIs('CASCADE') if force else None)
        res = self.execute_sql(query, params)
        return res

    def add_collaborator(self, repo, username, privileges=[]):
        # check that all repo names, usernames, and privileges passed aren't
        # sql injections
        self._check_for_injections(repo)
        self._check_for_injections(username)
        for privilege in privileges:
            self._check_for_injections(privilege)

        query = ('BEGIN;'
                 'GRANT USAGE ON SCHEMA %s TO %s;'
                 'GRANT %s ON ALL TABLES IN SCHEMA %s TO %s;'
                 'ALTER DEFAULT PRIVILEGES IN SCHEMA %s '
                 'GRANT %s ON TABLES TO %s;'
                 'COMMIT;'
                 )

        privileges_str = ', '.join(privileges)
        params = [repo, username, privileges_str, repo,
                  username, repo, privileges_str, username]
        params = tuple(map(lambda x: AsIs(x), params))
        self.execute_sql(query, params)

    def delete_collaborator(self, repo, username):
        self._check_for_injections(repo)
        self._check_for_injections(username)

        query = ('BEGIN;'
                 'REVOKE ALL ON ALL TABLES IN SCHEMA %s FROM %s CASCADE;'
                 'REVOKE ALL ON SCHEMA %s FROM %s CASCADE;'
                 'ALTER DEFAULT PRIVILEGES IN SCHEMA %s '
                 'REVOKE ALL ON TABLES FROM %s;'
                 'COMMIT;'
                 )
        params = [repo, username, repo, username, repo, username]
        params = tuple(map(lambda x: AsIs(x), params))

        self.execute_sql(query, params)

    def list_tables(self, repo):
        res = self.list_repos()
        self._check_for_injections(repo)

        all_repos = [t[0] for t in res['tuples']]
        if repo not in all_repos:
            raise LookupError('Invalid repository name: %s' % (repo))

        query = ('SELECT table_name FROM information_schema.tables '
                 'WHERE table_schema = %s AND table_type = \'BASE TABLE\';'
                 )
        params = (repo,)
        return self.execute_sql(query, params)

    def list_views(self, repo):
        res = self.list_repos()
        self._check_for_injections(repo)

        all_repos = [t[0] for t in res['tuples']]
        if repo not in all_repos:
            raise LookupError('Invalid repository name: %s' % (repo))

        query = ('SELECT table_name FROM information_schema.tables '
                 'WHERE table_schema = %s '
                 'AND table_type = \'VIEW\';')

        params = (repo,)
        return self.execute_sql(query, params)

    def get_schema(self, table):
        tokens = table.split('.')
        for token in tokens:
            self._check_for_injections(token)

        if len(tokens) < 2:
            raise NameError(
                "Invalid name: '%s'.\n"
                "HINT: use <repo-name>.<table-name> " % (table))

        query = ('SELECT column_name, data_type '
                 'FROM information_schema.columns '
                 'WHERE table_name = %s '
                 'AND table_schema = %s;'
                 )

        params = (tokens[-1], tokens[-2])
        res = self.execute_sql(query, params)

        if res['row_count'] < 1:
            raise NameError("Invalid reference: '%s'.\n" % (table))

        return res

    def execute_sql(self, query, params=None):
        result = {
            'status': False,
            'row_count': 0,
            'tuples': [],
            'fields': []
        }

        conn = self.connection
        cur = conn.cursor()
        cur.execute(query.strip(), params)

        try:
            result['tuples'] = cur.fetchall()
        except:
            pass

        result['status'] = True
        result['row_count'] = cur.rowcount
        if cur.description:
            result['fields'] = [
                {'name': col[0], 'type': col[1]} for col in cur.description]

        query.strip().split(' ', 2)
        cur.close()
        return result

    def create_user(self, username, password, create_db=True):
        self._check_for_injections(username)

        query = ('CREATE ROLE %s WITH LOGIN '
                 'NOCREATEDB NOCREATEROLE NOCREATEUSER PASSWORD %s')
        params = (AsIs(username), password)
        self.execute_sql(query, params)

        if create_db:
            return self.create_user_database(username)

    def create_user_database(self, username):
        # lines need to be executed seperately because
        # "CREATE DATABASE cannot be executed from a
        # function or multi-command string"
        self._check_for_injections(username)

        query = 'CREATE DATABASE %s; '
        params = (AsIs(username),)
        self.execute_sql(query, params)

        query = 'ALTER DATABASE %s OWNER TO %s; '
        params = (AsIs(username), AsIs(username))
        return self.execute_sql(query, params)

    def remove_user(self, username, remove_db=True):
        if remove_db:
            self.remove_database(username)

        self._check_for_injections(username)
        query = 'DROP ROLE %s;'
        params = (AsIs(username),)
        return self.execute_sql(query, params)

    def remove_database(self, username):
        # This is not safe. If a user has shared repos
        # with another user, it will crash.
        self._check_for_injections(username)
        query = 'DROP DATABASE %s;'
        params = (AsIs(username),)
        return self.execute_sql(query, params)

    def change_password(self, username, password):
        self._check_for_injections(username)
        query = 'ALTER ROLE %s WITH PASSWORD %s;'
        params = (AsIs(username), password)
        return self.execute_sql(query, params)

    def list_collaborators(self, repo_base, repo):
        query = 'SELECT unnest(nspacl) FROM pg_namespace WHERE nspname=%s;'
        params = (repo, )
        return self.execute_sql(query, params)

    def has_base_privilege(self, login, privilege):
        query = 'SELECT has_database_privilege(%s, %s);'
        params = (login, privilege)
        return self.execute_sql(query, params)

    def has_repo_privilege(self, login, repo, privilege):
        query = 'SELECT has_schema_privilege(%s, %s, %s);'
        params = (login, repo, privilege)
        return self.execute_sql(query, params)

    def has_table_privilege(self, login, table, privilege):
        query = 'SELECT has_table_privilege(%s, %s, %s);'
        params = (login, table, privilege)
        return self.execute_sql(query, params)

    def has_column_privilege(self, login, table, column, privilege):
        query = 'SELECT has_column_privilege(%s, %s, %s, %s);'
        params = (login, table, column, privilege)
        return self.execute_sql(query, params)

    def export_table(self, table_name, file_path, file_format='CSV',
                     delimiter=',', header=True):
        header_option = 'HEADER' if header else ''

        self._check_for_injections(table_name)
        self._check_for_injections(file_format)

        query = 'COPY %s TO %s WITH %s %s DELIMITER %s;'
        params = (AsIs(table_name), file_path,
                  AsIs(file_format), AsIs(header_option), delimiter)

        return self.execute_sql(query, params)

    def export_query(self, query, file_path, file_format='CSV',
                     delimiter=',', header=True):
        # warning: this method is inherently unsafe, since there's no way to
        # properly escape the query string, and it runs as root!

        # I've made it safer by stripping out everything after the semicolon
        # in the passed query.
        # manager.py should also check to ensure the user has repo/folder access
        # RogerTangos 2015-012-09

        header_option = 'HEADER' if header else ''
        query = query.split(';')[0] + ';'

        self._check_for_injections(file_format)
        self._check_for_injections(header_option)

        meta_query = 'COPY (%s) TO %s WITH %s %s DELIMITER %s;'
        params = (AsIs(query), file_path, AsIs(file_format),
                  AsIs(header_option), delimiter)

        return self.execute_sql(meta_query, params)

    def import_file(self, table_name, file_path, file_format='CSV',
                    delimiter=',', header=True, encoding='ISO-8859-1',
                    quote_character='"'):

        header_option = 'HEADER' if header else ''
        self._check_for_injections(table_name)
        self._check_for_injections(file_format)
        self._check_for_injections(header_option)

        query = 'COPY %s FROM %s WITH %s %s DELIMITER %s ENCODING %s QUOTE %s;'
        params = (AsIs(table_name), file_path, AsIs(file_format),
                  AsIs(header_option), delimiter, encoding, quote_character)
        try:
            self.execute_sql(query, params)
        except Exception,e:
            self.execute_sql('DROP TABLE IF EXISTS %s', (AsIs(table_name),))
            raise ImportError(e)

            # Try importing using dbtruck. Was never enabled by anant.
            # RogerTangos 2015-12-09
            # return self.import_file_w_dbtruck(table_name, file_path)

    def import_file_w_dbtruck(self, table_name, file_path):
        # dbtruck is not tested for safety. At all. It's currently disabled
        # in the project RogerTangos 2015-12-09
        from dbtruck.dbtruck import import_datafiles
        # from dbtruck.util import get_logger
        from dbtruck.exporters.pg import PGMethods

        dbsettings = {
            'dbname': self.repo_base,
            'hostname': self.host,
            'username': self.user,
            'password': self.password,
            'port': self.port,
        }

        create_new = True
        errfile = None

        return import_datafiles([file_path], create_new, table_name, errfile,
                                PGMethods, **dbsettings)
