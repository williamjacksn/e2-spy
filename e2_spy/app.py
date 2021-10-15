import config
import contextlib
import datetime
import flask
import io
import logging
import signal
import sys
import waitress
import werkzeug.exceptions
import xlsxwriter

from db import AppDatabase, E2Database

log = logging.getLogger(__name__)

logging.basicConfig(filename=str(config.APP_LOG), format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S', level=logging.DEBUG)


def str_to_date(s: str) -> datetime.date:
    return datetime.datetime.strptime(s, '%Y-%m-%d').date()


def get_database():
    """Get a connection to the database"""
    return AppDatabase(config.APP_DB_PATH)


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


@app.get('/')
def index():
    """Render the front page"""
    if flask.g.db.e2_database_configured:
        return flask.render_template('index.html')
    return flask.redirect(flask.url_for('settings'))


@app.get('/action-summary')
def action_summary():
    e2db = get_e2_database(flask.g.db)
    try:
        start_date = str_to_date(flask.request.values.get('start_date'))
    except (TypeError, ValueError):
        start_date = None
    try:
        end_date = str_to_date(flask.request.values.get('end_date'))
    except (TypeError, ValueError):
        end_date = None
    if start_date is None:
        if end_date is None:
            start_date = datetime.date.today().replace(day=1)
            end_date = datetime.date.today()
        else:
            start_date = end_date + datetime.timedelta(days=-30)
    else:
        if end_date is None:
            end_date = start_date + datetime.timedelta(days=30)
        elif start_date > end_date:
            start_date, end_date = end_date, start_date
    flask.g.start_date = start_date
    flask.g.end_date = end_date
    flask.g.selected_users = flask.request.values.getlist('users')
    flask.g.rows = e2db.action_summary(start_date, end_date, flask.g.selected_users)
    flask.g.available_users = e2db.get_followup_user_code_list()
    return flask.render_template('action-summary.html')


@app.get('/days-since-last-activity')
def days_since_last_activity():
    e2db = get_e2_database(flask.g.db)
    flask.g.rows = e2db.days_since_last_activity()
    flask.g.job_notes = flask.g.db.job_notes_list()
    return flask.render_template('days-since-last-activity.html')


@app.get('/days-since-last-activity.xlsx')
def days_since_last_activity_xlsx():
    e2db = get_e2_database(flask.g.db)
    rows = e2db.days_since_last_activity()
    notes = flask.g.db.job_notes_list()
    output = io.BytesIO()
    workbook_options = {
        'default_date_format': 'yyyy-mm-dd',
        'in_memory': True,
    }
    workbook = xlsxwriter.Workbook(output, workbook_options)
    text_wrap = workbook.add_format({'text_wrap': True})
    worksheet = workbook.add_worksheet()
    headers = [
        'Job Number', 'Part Number', 'Part Description', 'Current Step', 'Next Step', 'Actual Start Date',
        'Actual End Date', 'Days Since Last Activity', 'Job Notes'
    ]
    col_widths = [len(v) for v in headers]
    worksheet.write_row(0, 0, headers)
    for i, row in enumerate(rows, start=1):
        worksheet.write(i, 0, row['job_number'])
        col_widths[0] = max(14, len(row['job_number']))  # 14 is a good width for 'Job Number'
        worksheet.write(i, 1, row['part_number'])
        col_widths[1] = max(col_widths[1], len(row['part_number']))
        worksheet.write_string(i, 2, row['part_description'])
        col_widths[2] = max(col_widths[2], len(row['part_description']))
        worksheet.write(i, 3, row['current_step'])
        col_widths[3] = max(col_widths[3], len(row['current_step']))
        worksheet.write(i, 4, row['next_step'])
        col_widths[4] = max(col_widths[4], len(row['next_step']))
        worksheet.write(i, 5, row['actual_start_date'])
        col_widths[5] = max(col_widths[5], len(str(row['actual_start_date'])))
        worksheet.write(i, 6, row['actual_end_date'])
        col_widths[6] = max(col_widths[6], len(str(row['actual_end_date'])))
        worksheet.write(i, 7, row['days_since_last_activity'])
        col_widths[7] = max(col_widths[7], len(str(row['days_since_last_activity'])))
        worksheet.write_string(i, 8, notes.get(row['job_number'], ''), text_wrap)
        col_widths[8] = 40  # 40 is a good width for 'Job Notes'
    for i, width in enumerate(col_widths):
        worksheet.set_column(i, i, width)
    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(rows), len(headers) - 1)
    workbook.close()
    response = flask.make_response(output.getvalue())
    response.headers.update({
        'Content-Disposition': 'attachment; filename="Days Since Last Activity.xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    return response


@app.post('/job-notes')
def job_notes():
    for k, v in flask.request.values.lists():
        log.debug(f'{k}: {v}')
    db: AppDatabase = flask.g.db
    job_number = flask.request.values.get('job_number')
    notes = flask.request.values.get('notes')
    if notes:
        db.job_notes_update(job_number, notes)
    else:
        db.job_notes_delete(job_number)
    next_view = flask.request.values.get('next_view')
    return flask.redirect(flask.url_for(next_view))


@app.get('/loading-summary')
def loading_summary():
    """Render the Loading Summary report"""
    e2db = get_e2_database(flask.g.db)
    flask.g.selected_departments = flask.request.values.getlist('department')
    if not flask.g.selected_departments:
        flask.g.selected_departments = ['Processing']
    flask.g.rows = e2db.get_loading_summary(flask.g.selected_departments)
    flask.g.departments = e2db.get_departments_list()
    return flask.render_template('loading-summary.html')


@app.get('/loading-summary.xlsx')
def loading_summary_xlsx():
    """Generate the Loading Summary report as an Excel file"""
    e2db = get_e2_database(flask.g.db)
    selected_departments = flask.request.values.getlist('department')
    if not selected_departments:
        selected_departments = ['Processing']
    rows = e2db.get_loading_summary(selected_departments)
    output = io.BytesIO()
    workbook_options = {'default_date_format': 'yyyy-mm-dd', 'in_memory': True}
    workbook = xlsxwriter.Workbook(output, workbook_options)
    worksheet = workbook.add_worksheet()
    headers = [
        'Department', 'Job Number', 'Work Center', 'Priority', 'Part Number', 'Description', 'Qty to Make',
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


@app.get('/open-sales-report')
def open_sales_report():
    e2db = get_e2_database(flask.g.db)
    flask.g.rows = e2db.open_sales_report()
    flask.g.job_notes = flask.g.db.job_notes_list()
    return flask.render_template('open-sales-report.html')


@app.get('/open-sales-report.xlsx')
def open_sales_report_xlsx():
    e2db = get_e2_database(flask.g.db)
    rows = e2db.open_sales_report()
    notes = flask.g.db.job_notes_list()
    output = io.BytesIO()
    workbook_options = {'default_date_format': 'yyyy-mm-dd', 'in_memory': True}
    workbook = xlsxwriter.Workbook(output, workbook_options)
    text_wrap = workbook.add_format({'text_wrap': True})
    worksheet = workbook.add_worksheet()
    headers = [
        'Job Number', 'Job Priority', 'Order Type', 'Hold Status', 'Parent Job Number', 'Part Number',
        'Part Description', 'Current Step', 'Qty to Make', 'Qty Open', 'Customer Code', 'Customer PO', 'Sales Amount',
        'Order Date', 'Ship By Date', 'Scheduled End Date', 'Vendor', 'Vendor PO', 'PO Date', 'PO Due Date', 'Job Notes'
    ]
    col_widths = [len(v) for v in headers]
    worksheet.write_row(0, 0, headers)
    for i, row in enumerate(rows, start=1):
        worksheet.write_row(i, 0, row.values(), text_wrap)
        worksheet.write_string(i, len(headers) - 1, notes.get(row['job_number'], ''), text_wrap)
        # find maximum column widths
        col_widths = [max(col_widths[j], len(str(v))) for j, v in enumerate(row.values())]
    for i, width in enumerate(col_widths):
        # set column widths
        worksheet.set_column(i, i, width)
    workbook.close()
    response = flask.make_response(output.getvalue())
    response.headers.update({
        'Content-Disposition': 'attachment; filename="Open Sales Report.xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    })
    return response


@app.get('/settings')
def settings():
    """Render the /settings page"""
    return flask.render_template('settings.html')


@app.post('/settings/save')
def settings_save():
    """Handle a POST request to save settings to the database"""
    flask.g.db.e2_database = flask.request.values.get('e2-database')
    flask.g.db.e2_hostname = flask.request.values.get('e2-hostname')
    flask.g.db.e2_password = flask.request.values.get('e2-password')
    flask.g.db.e2_user = flask.request.values.get('e2-user')
    return flask.redirect(flask.url_for('index'))


def main():
    waitress.serve(app, port=config.PORT, threads=8)


def handle_sigterm(_signal, _frame):
    sys.exit()


if __name__ == '__main__':
    with open(config.ERR_LOG, 'a') as f, contextlib.redirect_stderr(f):
        signal.signal(signal.SIGTERM, handle_sigterm)
        main()
