import logging
import psycopg2
import psycopg2.extras
import psycopg2.pool

from typing import Any, Dict, List, Optional


class PostgresDatabase:
    def __init__(self, dsn, minconn=1, maxconn=1):
        self.log = logging.getLogger(__name__)
        self.p = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn, cursor_factory=psycopg2.extras.DictCursor)
        psycopg2.extras.register_uuid()

    def q(self, sql: str, params: Dict = None) -> List[Dict]:
        """Execute a query and return all rows"""
        if params is None:
            params = {}
        cnx = self.p.getconn()
        cnx.autocommit = True
        with cnx.cursor() as c:
            self.log.debug(c.mogrify(sql, params).decode())
            c.execute(sql, params)
            result = c.fetchall()
        self.p.putconn(cnx)
        return result

    def q_one(self, sql: str, params: Dict = None) -> Optional[Dict]:
        """Execute a query and return the first row, or None if there are no rows"""
        for r in self.q(sql, params):
            return r
        return None

    def q_val(self, sql: str, params: Dict = None) -> Any:
        """Execute a query and return the value in the first column of the first row, or None if there are no rows"""
        for r in self.q(sql, params):
            return r[0]
        return None

    def u(self, sql: str, params: Dict = None) -> int:
        """Execute a statement and return the number of rows affected"""
        if params is None:
            params = {}
        cnx = self.p.getconn()
        cnx.autocommit = True
        with cnx.cursor() as c:
            self.log.debug(c.mogrify(sql, params).decode())
            c.execute(sql, params)
            result = c.rowcount
        self.p.putconn(cnx)
        return result
