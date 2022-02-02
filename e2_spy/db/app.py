import datetime
import fort
import secrets


class AppDatabase(fort.SQLiteDatabase):
    _version: int = None

    @property
    def e2_database_configured(self) -> bool:
        for prop in ('e2-database', 'e2-hostname', 'e2-password', 'e2-user'):
            if self.get_setting(prop) in (None, ''):
                return False
        return True

    @property
    def e2_database(self) -> str:
        return self.get_setting('e2-database')

    @e2_database.setter
    def e2_database(self, value: str):
        self.set_setting('e2-database', value)

    @property
    def e2_hostname(self) -> str:
        return self.get_setting('e2-hostname')

    @e2_hostname.setter
    def e2_hostname(self, value: str):
        self.set_setting('e2-hostname', value)

    @property
    def e2_password(self) -> str:
        return self.get_setting('e2-password')

    @e2_password.setter
    def e2_password(self, value: str):
        self.set_setting('e2-password', value)

    @property
    def e2_user(self) -> str:
        return self.get_setting('e2-user')

    @e2_user.setter
    def e2_user(self, value: str):
        self.set_setting('e2-user', value)

    @property
    def secret_key(self) -> bytes:
        return bytes.fromhex(self.get_setting('secret-key'))

    @secret_key.setter
    def secret_key(self, value: bytes):
        self.set_setting('secret-key', value.hex())

    def get_setting(self, setting_id: str) -> str:
        sql = '''
            select setting_value from settings where setting_id = :setting_id
        '''
        params = {
            'setting_id': setting_id
        }
        return self.q_val(sql, params)

    def set_setting(self, setting_id: str, setting_value: str):
        sql = '''
            insert into settings (setting_id, setting_value)
            values (:setting_id, :setting_value)
            on conflict (setting_id) do update set setting_value = :setting_value
        '''
        params = {
            'setting_id': setting_id,
            'setting_value': setting_value
        }
        self.u(sql, params)

    def job_notes_delete(self, job_number: str):
        sql = '''
            delete from job_notes where job_number = :job_number
        '''
        params = {
            'job_number': job_number
        }
        self.u(sql, params)

    def job_notes_list(self):
        sql = '''
            select job_number, notes
            from job_notes
        '''
        return {r['job_number']: r['notes'] for r in self.q(sql)}

    def job_notes_update(self, job_number: str, notes: str):
        sql = '''
            insert into job_notes (job_number, notes) values (:job_number, :notes)
            on conflict (job_number) do update set notes = :notes 
        '''
        params = {
            'job_number': job_number,
            'notes': notes
        }
        self.u(sql, params)

    def add_schema_version(self, schema_version: int):
        """Add a schema version to the database."""
        self._version = schema_version
        sql = '''
            insert into schema_versions (schema_version, migration_timestamp)
            values (:schema_version, :migration_timestamp)
        '''
        params = {
            'schema_version': schema_version,
            'migration_timestamp': datetime.datetime.now(datetime.timezone.utc)
        }
        self.u(sql, params)

    def migrate(self):
        """Run database migrations."""
        self.log.info(f'Database schema version is {self.version}')
        if self.version < 1:
            self.log.info('Migrating database to schema version 1')
            self.u('''
                create table schema_versions (
                    schema_version integer primary key,
                    migration_timestamp timestamp
                )
            ''')
            self.u('''
                create table settings (
                    setting_id text primary key,
                    setting_value text
                )
            ''')
            self.secret_key = secrets.token_bytes()
            self.add_schema_version(1)
        if self.version < 2:
            self.log.info('Migrating database to schema version 2')
            self.u('''
                create table job_notes (
                    job_number text primary key,
                    notes text
                )
            ''')
            self.add_schema_version(2)
        if self.version < 3:
            self.log.info('Migrating database to schema version 3')
            self.u('''
                create table page_passwords (
                    page_key text primary key,
                    page_password text not null
                )
            ''')
            self.u('''
                create table unlocked_pages (
                    session_id text,
                    page_key text
                )
            ''')
            self.add_schema_version(3)

    def _table_exists(self, table_name: str) -> bool:
        sql = '''
            select count(*) table_count from sqlite_master where type = :type and name = :table_name
        '''
        params = {
            'type': 'table',
            'table_name': table_name
        }
        for record in self.q(sql, params):
            if record['table_count'] == 0:
                return False
        return True

    @property
    def version(self) -> int:
        """Get the schema version for this database."""
        if self._version is None:
            self._version = 0
            if self._table_exists('schema_versions'):
                sql = '''
                    select max(schema_version) current_version from schema_versions
                '''
                current_version = self.q_val(sql)
                if current_version is not None:
                    self._version = current_version
        return self._version
