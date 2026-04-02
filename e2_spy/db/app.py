import datetime as dt
import json
import secrets
from typing import TypedDict

import fort


class PaperlessPartsQuoteItemsDict(TypedDict):
    quote_number: int
    revision: int
    part_number: str
    part_name: str
    part_revision: str
    quote_sent_date: dt.datetime


class AppDatabase(fort.SQLiteDatabase):
    _version: int | None = None

    def _table_exists(self, table_name: str) -> bool:
        sql = """
            select count(*) table_count
            from sqlite_master where type = :type and name = :table_name
        """
        params = {"type": "table", "table_name": table_name}
        for record in self.q(sql, params):
            if record["table_count"] == 0:
                return False
        return True

    def add_schema_version(self, schema_version: int) -> None:
        """Add a schema version to the database."""
        self._version = schema_version
        sql = """
            insert into schema_versions (schema_version, migration_timestamp)
            values (:schema_version, :migration_timestamp)
        """
        params = {
            "schema_version": schema_version,
            "migration_timestamp": dt.datetime.now(dt.UTC),
        }
        self.u(sql, params)

    def check_page_password(self, page_key: str, password: str) -> bool:
        sql = """
            select page_password from page_passwords where page_key = :page_key
        """
        params = {"page_key": page_key}
        page_password = self.q_val(sql, params)
        return password == page_password

    @property
    def e2_database(self) -> str:
        return self.get_setting("e2-database")

    @e2_database.setter
    def e2_database(self, value: str) -> None:
        self.set_setting("e2-database", value)

    @property
    def e2_database_configured(self) -> bool:
        for prop in ("e2-database", "e2-hostname", "e2-password", "e2-user"):
            if self.get_setting(prop) in (None, ""):
                return False
        return True

    @property
    def e2_hostname(self) -> str:
        return self.get_setting("e2-hostname")

    @e2_hostname.setter
    def e2_hostname(self, value: str) -> None:
        self.set_setting("e2-hostname", value)

    @property
    def e2_password(self) -> str:
        return self.get_setting("e2-password")

    @e2_password.setter
    def e2_password(self, value: str) -> None:
        self.set_setting("e2-password", value)

    @property
    def e2_user(self) -> str:
        return self.get_setting("e2-user")

    @e2_user.setter
    def e2_user(self, value: str) -> None:
        self.set_setting("e2-user", value)

    def get_setting(self, setting_id: str) -> str:
        sql = """
            select setting_value from settings where setting_id = :setting_id
        """
        params = {"setting_id": setting_id}
        return self.q_val(sql, params)

    def get_unlocked_pages(self, session_id: str) -> list[str]:
        sql = """
            select page_key
            from unlocked_pages
            where session_id = :session_id
            order by page_key
        """
        params = {"session_id": session_id}
        return [r["page_key"] for r in self.q(sql, params)]

    def job_notes_delete(self, job_number: str) -> None:
        sql = """
            delete from job_notes where job_number = :job_number
        """
        params = {"job_number": job_number}
        self.u(sql, params)

    def job_notes_get(self, job_number: str) -> str:
        sql = """
            select notes
            from job_notes
            where job_number = :job_number
        """
        params = {"job_number": job_number}
        for row in self.q(sql, params):
            return row["notes"]
        return ""

    def job_notes_update(self, job_number: str, notes: str) -> None:
        sql = """
            insert into job_notes (job_number, notes) values (:job_number, :notes)
            on conflict (job_number) do update set notes = :notes 
        """
        params = {"job_number": job_number, "notes": notes}
        self.u(sql, params)

    def lock_page(self, session_id: str, page_key: str) -> None:
        sql = """
            delete from unlocked_pages
            where session_id = :session_id and page_key = :page_key
        """
        params = {"page_key": page_key, "session_id": session_id}
        self.u(sql, params)

    def migrate(self) -> None:
        """Run database migrations."""
        self.log.info(f"Database schema version is {self.version}")
        if self.version < 1:
            self.log.info("Migrating database to schema version 1")
            self.u("""
                create table schema_versions (
                    schema_version integer primary key,
                    migration_timestamp timestamp
                )
            """)
            self.u("""
                create table settings (
                    setting_id text primary key,
                    setting_value text
                )
            """)
            self.secret_key = secrets.token_bytes()
            self.add_schema_version(1)
        if self.version < 2:
            self.log.info("Migrating database to schema version 2")
            self.u("""
                create table job_notes (
                    job_number text primary key,
                    notes text
                )
            """)
            self.add_schema_version(2)
        if self.version < 3:
            self.log.info("Migrating database to schema version 3")
            self.u("""
                create table page_passwords (
                    page_key text primary key,
                    page_password text not null
                )
            """)
            self.u("""
                create table unlocked_pages (
                    session_id text,
                    page_key text
                )
            """)
            self.add_schema_version(3)
        if self.version < 4:
            self.log.info("Migrating database to schema version 4")
            self.u("""
                create table paperless_parts_quote_revisions (
                    quote_number int not null,
                    revision_number int
                )
            """)
            self.u("""
                create table paperless_parts_quote_details (
                    quote_number int not null,
                    revision_number int,
                    id int,
                    uuid uuid,
                    due_date datetime,
                    sent_date datetime,
                    quote_notes text,
                    created datetime,
                    payload text
                )
            """)
            self.u("""
                create table paperless_parts_quote_items (
                    quote_number int not null,
                    revision number int,
                    part_number text,
                    part_name text,
                    part_revision text
                )
            """)
            self.add_schema_version(4)
        if self.version < 5:
            self.log.info("Migrating database to schema version 5")
            self.u("""
                alter table paperless_parts_quote_items
                add column quote_sent_date datetime
            """)
            self.add_schema_version(5)

    @property
    def paperless_parts_api_key(self) -> str:
        return self.get_setting("paperless-parts-api-key")

    @paperless_parts_api_key.setter
    def paperless_parts_api_key(self, value: str) -> None:
        self.set_setting("paperless-parts-api-key", value)

    def paperless_parts_quote_details_delete_all(self) -> None:
        sql = """
            delete from paperless_parts_quote_details
        """
        self.u(sql)

    def paperless_parts_quote_details_get(
        self, quote_number: int, revision_number: int | None
    ) -> dict | None:
        if revision_number is None:
            where_clause = "quote_number = :quote_number and revision_number is null"
        else:
            where_clause = (
                "quote_number = :quote_number and revision_number = :revision_number"
            )
        sql = f"""
            select
                created, due_date, id, payload, quote_notes, quote_number,
                revision_number, sent_date, uuid
            from paperless_parts_quote_details
            where {where_clause}
        """  # noqa: S608
        params = {"quote_number": quote_number, "revision_number": revision_number}
        return self.q_one(sql, params)

    def paperless_parts_quote_details_get_last_sent(self) -> dict | None:
        sql = """
            select quote_number, revision_number
            from paperless_parts_quote_details
            order by sent_date desc
            limit 1
        """
        return self.q_one(sql)

    def paperless_parts_quote_details_insert(self, payload: dict) -> None:
        sql = """
            insert into paperless_parts_quote_details (
                created, due_date, id, payload, quote_notes, quote_number,
                revision_number, sent_date, uuid
            ) values (
                :created, :due_date, :id, :payload, :quote_notes, :quote_number,
                :revision_number, :sent_date, :uuid
            )
        """
        params = {
            "created": payload["created"],
            "due_date": payload["due_date"],
            "id": payload["id"],
            "payload": json.dumps(payload),
            "quote_notes": payload["quote_notes"],
            "quote_number": payload["number"],
            "revision_number": payload["revision_number"],
            "sent_date": payload["sent_date"],
            "uuid": payload["uuid"],
        }
        self.u(sql, params)

    def paperless_parts_quote_details_list_for_quote(self, quote_number: int) -> list:
        sql = """
            select
                created, due_date, id, payload, quote_notes, quote_number,
                revision_number, sent_date, uuid
            from paperless_parts_quote_details
            where quote_number = :quote_number
            order by revision_number nulls first
        """
        params = {"quote_number": quote_number}
        return self.q(sql, params)

    def paperless_parts_quote_items_parts_in_range(
        self, start_date: dt.date, end_date: dt.date
    ) -> list[str]:
        sql = """
            select distinct part_number
            from paperless_parts_quote_items
            where part_number is not null
            and quote_sent_date > :start_date
            and quote_sent_date < :end_date
            order by part_number
        """
        params = {"start_date": start_date, "end_date": end_date}
        return [r["part_number"] for r in self.q(sql, params)]

    def paperless_parts_quote_items_reset(
        self, quote_number: int, quote_revision: int | None
    ) -> None:
        if quote_revision is None:
            rev_condition = "is null"
        else:
            rev_condition = "= :revision"
        sql = f"""
            delete from paperless_parts_quote_items
            where quote_number = :quote_number and revision {rev_condition}
        """  # noqa: S608
        params = {"quote_number": quote_number, "revision": quote_revision}
        self.u(sql, params)

    def paperless_parts_quote_items_insert(
        self, params: PaperlessPartsQuoteItemsDict
    ) -> None:
        sql = """
            insert into paperless_parts_quote_items (
                quote_number, revision, part_number, part_name, part_revision,
                quote_sent_date
            ) values (
                :quote_number, :revision, :part_number, :part_name, :part_revision,
                :quote_sent_date
            )
        """
        self.u(sql, params)  # ty:ignore[invalid-argument-type]

    def paperless_parts_quote_revisions_insert(
        self, quote_number: int, revision_number: int | None
    ) -> None:
        sql = """
            insert into paperless_parts_quote_revisions (
                quote_number, revision_number
            ) values (
                :quote_number, :revision_number
            )
        """
        params = {"quote_number": quote_number, "revision_number": revision_number}
        self.u(sql, params)

    def paperless_parts_quote_revisions_list(self) -> list:
        sql = """
            select quote_number, revision_number
            from paperless_parts_quote_revisions
        """
        return self.q(sql)

    @property
    def secret_key(self) -> bytes:
        return bytes.fromhex(self.get_setting("secret-key"))

    @secret_key.setter
    def secret_key(self, value: bytes) -> None:
        self.set_setting("secret-key", value.hex())

    def set_setting(self, setting_id: str, setting_value: str) -> None:
        sql = """
            insert into settings (setting_id, setting_value)
            values (:setting_id, :setting_value)
            on conflict (setting_id) do update set setting_value = :setting_value
        """
        params = {"setting_id": setting_id, "setting_value": setting_value}
        self.u(sql, params)

    def unlock_page(self, session_id: str, page_key: str) -> None:
        self.lock_page(session_id, page_key)
        sql = """
            insert into unlocked_pages (session_id, page_key)
            values (:session_id, :page_key)
        """
        params = {
            "page_key": page_key,
            "session_id": session_id,
        }
        self.u(sql, params)

    @property
    def version(self) -> int:
        """Get the schema version for this database."""
        if self._version is None:
            self._version = 0
            if self._table_exists("schema_versions"):
                sql = """
                    select max(schema_version) current_version from schema_versions
                """
                current_version = self.q_val(sql)
                if current_version is not None:
                    self._version = current_version
        return self._version
