import contextlib
import flask
import io
import logging
import os
import pathlib
import signal
import sys
import waitress
import werkzeug.exceptions
import xlsxwriter

from db import AppDatabase, E2Database

log = logging.getLogger(__name__)

LOCAL_DIR = pathlib.Path(os.getenv('LOCAL_DIR', '../.local')).resolve()
ERR_LOG = LOCAL_DIR / 'stderr.log'
APP_LOG = LOCAL_DIR / 'app.log'
logging.basicConfig(filename=str(APP_LOG), format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S', level=logging.DEBUG)

DB_PATH = LOCAL_DIR / 'app.db'


def get_database():
    """Get a connection to the database"""
    return AppDatabase(DB_PATH)


def get_e2_database(_db: AppDatabase) -> E2Database:
    cnx_details = {
        'server': _db.e2_hostname,
        'user': _db.e2_user,
        'password': _db.e2_password,
        'database': _db.e2_database
    }
    return E2Database(cnx_details)


app = flask.Flask(__name__)

app_db = get_database()
app_db.migrate()
app.secret_key = app_db.secret_key


@app.errorhandler(werkzeug.exceptions.InternalServerError)
def handle_internal_server_error(e):
    flask.g.exception = e.original_exception
    return flask.render_template('internal-server-error.html')


@app.before_request
def before_request():
    """Open a database connection before each request"""
    flask.g.db = get_database()


@app.route('/')
def index():
    """Render the front page"""
    if flask.g.db.e2_database_configured:
        return flask.render_template('index.html')
    return flask.redirect(flask.url_for('settings'))


@app.route('/loading-summary')
def loading_summary():
    """Render the Loading Summary report"""
    e2db = get_e2_database(flask.g.db)
    flask.g.selected_department = flask.request.values.get('department', 'Processing')
    flask.g.rows = e2db.get_loading_summary(flask.g.selected_department)
    flask.g.departments = e2db.get_departments_list()
    return flask.render_template('loading-summary.html')


@app.route('/loading-summary.xlsx')
def loading_summary_xlsx():
    """Generate the Loading Summary report as an Excel file"""
    e2db = get_e2_database(flask.g.db)
    department_name = flask.request.values.get('department_name', 'Processing')
    rows = e2db.get_loading_summary(department_name)
    output = io.BytesIO()
    workbook_options = {'default_date_format': 'yyyy-mm-dd', 'in_memory': True}
    workbook = xlsxwriter.Workbook(output, workbook_options)
    worksheet = workbook.add_worksheet()
    headers = [
        'Job Number', 'Work Center', 'Priority', 'Part Number', 'Description', 'Qty to Make',
        'Qty Open', 'Start Date', 'End Date', 'Due Date', 'Next Step'
    ]
    col_widths = [len(v) for v in headers]
    worksheet.write_row(0, 0, headers)
    for i, row in enumerate(rows, start=1):
        worksheet.write_row(i, 0, row.values())
        # find maximum column widths
        col_widths = [max(col_widths[j], len(str(v))) for j, v in enumerate(row.values())]
    for i, width in enumerate(col_widths):
        # set column widths
        worksheet.set_column(i, i, width)
    workbook.close()
    response = flask.make_response(output.getvalue())
    response.headers.update({
        'Content-Disposition': 'attachment; filename="Loading Summary.xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    })
    return response


@app.route('/settings')
def settings():
    """Render the /settings page"""
    return flask.render_template('settings.html')


@app.route('/settings/save', methods=['post'])
def settings_save():
    """Handle a POST request to save settings to the database"""
    flask.g.db.e2_database = flask.request.values.get('e2-database')
    flask.g.db.e2_hostname = flask.request.values.get('e2-hostname')
    flask.g.db.e2_password = flask.request.values.get('e2-password')
    flask.g.db.e2_user = flask.request.values.get('e2-user')
    return flask.redirect(flask.url_for('index'))


def main(port: int = None):
    """Serve the app on the specified port"""
    if port is None:
        port = 8080
    waitress.serve(app, host='localhost', port=port, threads=8)


def handle_sigterm(_signal, _frame):
    sys.exit()


if __name__ == '__main__':
    with open(ERR_LOG, 'a') as f, contextlib.redirect_stderr(f):
        signal.signal(signal.SIGTERM, handle_sigterm)
        main()
