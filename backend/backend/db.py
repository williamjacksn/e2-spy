import contextlib
import fort
import pymssql
import secrets
import urllib.parse


class E2Database:
    def __init__(self, cnx_details: dict):
        self.cnx = pymssql.connect(**cnx_details, as_dict=True)

    def q(self, sql: str, params: tuple = None):
        if params is None:
            params = tuple()
        with contextlib.closing(self.cnx.cursor()) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def get_departments_list(self) -> list[str]:
        sql = '''
            select distinct department_name
            from schedule_detail
            where len(department_name) > 0
            order by department_name
        '''
        return [row.get('department_name') for row in self.q(sql)]

    def get_loading_summary(self, department_name: str):
        sql = '''
            select
                sd.job_number,
                sd.work_center,
                sd.priority,
                sd.part_number,
                sd.part_description,
                sd.quantity_to_make,
                sd.quantity_open,
                sd.scheduled_start_date start_date,
                sd.scheduled_end_date end_date,
                sd.due_date,
                coalesce(ns.work_center, ns.vendor_code, 'LAST STEP') next_step
            from schedule_detail sd
            left join schedule_detail ns on ns.schedule_job_id = sd.schedule_job_id and ns.item_number = sd.item_number + 1
            where sd.department_name = %s
            and sd.step_status in ('Current', 'Pending')
            and sd.scheduled_start_date < %s
            order by sd.due_date
        '''
        params = (
            department_name,
            pymssql.datetime.date.today() + pymssql.datetime.timedelta(days=1)
        )
        return self.q(sql, params)


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

    def add_schema_version(self, schema_version: int):
        """Add a schema version to the database."""
        self._version = schema_version
        sql = '''
            insert into schema_versions (schema_version, migration_timestamp)
            values (:schema_version, :migration_timestamp)
        '''
        params = {
            'schema_version': schema_version,
            'migration_timestamp': pymssql.datetime.datetime.now(pymssql.datetime.timezone.utc)
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

    def _table_exists(self, table_name: str) -> bool:
        sql = '''
            select count(*) table_count from sqlite_schema where type = :type and name = :table_name
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
