import warnings

try:
    from .postgres import PostgresDatabase
except ModuleNotFoundError:
    warnings.warn('PostgresDatabase will not be available', ImportWarning)

from .sqlite import SQLiteDatabase

__version__ = '1.0.1'
