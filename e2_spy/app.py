import config
import contextlib
import datetime
import flask
import functools
import io
import logging
import pathlib
import secrets
import signal
import sys
import waitress
import werkzeug.exceptions
import whitenoise
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

whitenoise_root = pathlib.Path(__file__).resolve().with_name('static')
app.wsgi_app = whitenoise.WhiteNoise(app.wsgi_app, root=whitenoise_root, prefix='static/')

app_db = get_database()
app_db.migrate()
app.secret_key = app_db.secret_key


@app.errorhandler(werkzeug.exceptions.InternalServerError)
def handle_internal_server_error(e):
    flask.g.exception = e.original_exception
    return flask.render_template('internal-server-error.html')


@app.before_request
def before_request():
    log.debug(f'{flask.request.method} {flask.request.path} -> {flask.request.endpoint}')
    flask.g.db = get_database()
    flask.session.permanent = True
    flask.g.session_id = flask.session.setdefault('session_id', secrets.token_urlsafe())
    flask.g.unlocked_pages = flask.g.db.get_unlocked_pages(flask.g.session_id)


def page_lock(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        log.debug(f'Checking if session {flask.g.session_id} has unlocked page {flask.request.endpoint}')
        if flask.request.endpoint in flask.g.unlocked_pages:
            log.debug('Page is unlocked')
            flask.g.unlocked = True
        else:
            log.debug('Page is locked')
            return flask.render_template('locked-page.html')
        return f(*args, **kwargs)
    return decorated_function


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


@app.get('/closed-jobs')
def closed_jobs():
    e2db = get_e2_database(flask.g.db)
    flask.g.rows = e2db.closed_jobs()
    flask.g.job_notes = flask.g.db.job_notes_list()
    return flask.render_template('closed-jobs.html')


@app.get('/closed-jobs.xlsx')
def closed_jobs_xlsx():
    e2db = get_e2_database(flask.g.db)
    rows = e2db.closed_jobs()
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
        'Job Number', 'Part Number', 'Part Description', 'Order Number', 'Customer Code', 'Customer PO Number',
        'Date Closed', 'Job Notes'
    ]
    col_widths = [len(v) for v in headers]
    col_names = [
        'job_number', 'part_number', 'part_description', 'order_number', 'customer_code', 'customer_po_number',
        'date_closed', 'job_notes'
    ]
    for i, row in enumerate(rows, start=1):
        for j, col_name in enumerate(col_names):
            if col_name == 'job_notes':
                col_data = notes.get(row['job_number'], '')
                col_widths[j] = 40
                worksheet.write_string(i, j, col_data, text_wrap)
            else:
                col_data = row[col_name]
                col_widths[j] = max(col_widths[j], len(str(col_data)))
                worksheet.write(i, j, col_data)
    for i, width in enumerate(col_widths):
        worksheet.set_column(i, i, width)
    table_options = {
        'name': 'ClosedJobs',
        'columns': [{'header': h} for h in headers]
    }
    worksheet.add_table(0, 0, len(rows), len(headers) - 1, table_options)
    workbook.close()
    response = flask.make_response(output.getvalue())
    response.headers.update({
        'Content-Disposition': 'attachment; filename="Closed Jobs.xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    return response


@app.get('/contacts')
def contacts():
    e2db = get_e2_database(flask.g.db)
    flask.g.rows = e2db.contacts_list()
    return flask.render_template('contacts.html')


@app.get('/contacts.xlsx')
def contacts_xlsx():
    e2db = get_e2_database(flask.g.db)
    rows = e2db.contacts_list()
    output = io.BytesIO()
    workbook_options = {
        'in_memory': True,
    }
    workbook = xlsxwriter.Workbook(output, workbook_options)
    worksheet = workbook.add_worksheet()
    headers = ['Contact Type', 'Customer Name', 'Vendor Name', 'Contact Name', 'Phone Number', 'Email', 'Title']
    col_widths = [len(v) for v in headers]
    col_names = ['contact_type', 'customer_name', 'vendor_name', 'contact_name', 'phone_number', 'email', 'title']
    for i, row in enumerate(rows, start=1):
        for j, col_name in enumerate(col_names):
            col_data = row[col_name]
            col_widths[j] = max(col_widths[j], len(str(col_data)))
            worksheet.write(i, j, col_data)
    for i, width in enumerate(col_widths):
        worksheet.set_column(i, i, width)
    table_options = {
        'name': 'Contacts',
        'columns': [{'header': h} for h in headers]
    }
    worksheet.add_table(0, 0, len(rows), len(headers) - 1, table_options)
    workbook.close()
    response = flask.make_response(output.getvalue())
    filename = 'Contacts.xlsx'
    response.headers.update({
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    })
    return response


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
    col_names = [
        'job_number', 'part_number', 'part_description', 'current_step', 'next_step', 'actual_start_date',
        'actual_end_date', 'days_since_last_activity', 'job_notes'
    ]
    for i, row in enumerate(rows, start=1):
        for j, col_name in enumerate(col_names):
            if col_name == 'job_number':
                col_data = row[col_name]
                worksheet.write(i, j, col_data)
                col_widths[j] = max(14, len(col_data))  # 14 is a good width for 'Job Number'
            elif col_name == 'part_description':
                col_data = row[col_name]
                worksheet.write_string(i, j, col_data)
                col_widths[j] = max(col_widths[j], len(col_data))
            elif col_name == 'job_notes':
                col_data = notes.get(row['job_number'], '')
                worksheet.write_string(i, j, col_data, text_wrap)
                col_widths[j] = 40  # 40 is a good width for 'Job Notes'
            else:
                col_data = row[col_name]
                worksheet.write(i, j, col_data)
                col_widths[j] = max(col_widths[j], len(str(col_data)))
    for i, width in enumerate(col_widths):
        worksheet.set_column(i, i, width)
    table_options = {
        'name': 'DaysSinceLastActivity',
        'columns': [{'header': h} for h in headers]
    }
    worksheet.add_table(0, 0, len(rows), len(headers) - 1, table_options)
    workbook.close()
    response = flask.make_response(output.getvalue())
    response.headers.update({
        'Content-Disposition': 'attachment; filename="Days Since Last Activity.xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    return response


@app.get('/income-statements')
@page_lock
def income_statements():
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
            start_date = end_date.replace(day=1)
    else:
        if end_date is None:
            end_date = datetime.date.today()
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    flask.g.start_date = start_date
    flask.g.end_date = end_date
    flask.g.department = flask.request.values.get('department', 'shop')
    e2db = get_e2_database(flask.g.db)
    flask.g.rows = e2db.income_statement(flask.g.department, flask.g.start_date, flask.g.end_date)
    flask.g.period_list = e2db.period_list(flask.g.start_date, flask.g.end_date)
    flask.g.total = sum([
        row.get('total_amount') for row in flask.g.rows
        if row.get('gl_group_code') in ('40', '50', '60', '70', '80', '90', '99')
    ])
    flask.g.revenue_total = sum([
        row.get('total_amount') for row in flask.g.rows
        if row.get('gl_group_code') in ('40', '90')
    ])
    flask.g.expense_total = sum([
        row.get('total_amount') for row in flask.g.rows
        if row.get('gl_group_code') in ('50', '60', '70', '80', '99')
    ])
    return flask.render_template('income-statements.html')


@app.get('/income-statements.xlsx')
@page_lock
def income_statements_xlsx():
    e2db = get_e2_database(flask.g.db)
    department = flask.request.values.get('department')
    start_date = str_to_date(flask.request.values.get('start_date'))
    end_date = str_to_date(flask.request.values.get('end_date'))
    rows = e2db.income_statement(department, start_date, end_date)
    output = io.BytesIO()
    workbook_options = {
        'default_date_format': 'yyyy-mm-dd',
        'in_memory': True,
    }
    workbook = xlsxwriter.Workbook(output, workbook_options)
    worksheet = workbook.add_worksheet()
    headers = ['GL Code', 'Account Description', 'Account Type', 'Amount']
    col_widths = [len(v) for v in headers]
    worksheet.write_row(0, 0, headers)
    col_names = ['gl_account', 'description', 'account_type', 'total_amount']
    for i, row in enumerate(rows, start=1):
        for j, col_name in enumerate(col_names):
            col_data = row[col_name]
            if col_name == 'gl_account':
                col_widths[j] = max(10, len(str(col_data)))
            else:
                col_widths[j] = max(col_widths[j], len(str(col_data)))
            worksheet.write(i, j, col_data)
    for i, width in enumerate(col_widths):
        worksheet.set_column(i, i, width)
    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(rows), len(headers) - 1)
    workbook.close()
    response = flask.make_response(output.getvalue())
    filename = f'Income Statement ({department}, {start_date} to {end_date}).xlsx'
    response.headers.update({
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
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


@app.get('/job-performance')
def job_performance():
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
            start_date = datetime.date.today() - datetime.timedelta(days=7)
            end_date = datetime.date.today()
        else:
            start_date = end_date + datetime.timedelta(days=-7)
    else:
        if end_date is None:
            end_date = start_date + datetime.timedelta(days=7)
        elif start_date > end_date:
            start_date, end_date = end_date, start_date
    flask.g.start_date = start_date
    flask.g.end_date = end_date
    flask.g.rows = e2db.job_performance(start_date, end_date)
    flask.g.job_notes = flask.g.db.job_notes_list()
    return flask.render_template('job-performance.html')


@app.get('/job-performance.xlsx')
def job_performance_xlsx():
    e2db = get_e2_database(flask.g.db)
    get_all = flask.request.values.get('get_all') == 'true'
    start_date = str_to_date(flask.request.values.get('start_date', '2022-01-01'))
    end_date = str_to_date(flask.request.values.get('end_date', '2022-01-01'))
    rows = e2db.job_performance(start_date, end_date, get_all)
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
        'Job Number', 'Part Number', 'Part Description', 'Product Code', 'Date Closed', 'Estimated Hours',
        'Actual Hours', 'Performance', 'Job Notes'
    ]
    col_widths = [len(v) for v in headers]
    col_names = [
        'job_number', 'part_number', 'part_description', 'product_code', 'date_closed', 'total_estimated_hours',
        'total_actual_hours', 'performance', 'job_notes'
    ]
    for i, row in enumerate(rows, start=1):
        for j, col_name in enumerate(col_names):
            if col_name == 'job_notes':
                col_data = notes.get(row['job_number'], '')
                col_widths[j] = 40
                worksheet.write_string(i, j, col_data, text_wrap)
            else:
                col_data = row[col_name]
                col_widths[j] = max(col_widths[j], len(str(col_data)))
                worksheet.write(i, j, col_data)
    for i, width in enumerate(col_widths):
        worksheet.set_column(i, i, width)
    table_options = {
        'name': 'JobPerformance',
        'columns': [{'header': h} for h in headers]
    }
    worksheet.add_table(0, 0, len(rows), len(headers) - 1, table_options)
    workbook.close()
    response = flask.make_response(output.getvalue())
    if get_all:
        record_range = 'all'
    else:
        record_range = f'{start_date} to {end_date}'
    response.headers.update({
        'Content-Disposition': f'attachment; filename="Job Performance ({record_range}).xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    })
    return response


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
    for i, row in enumerate(rows, start=1):
        worksheet.write_row(i, 0, row.values())
        # find maximum column widths
        col_widths = [max(col_widths[j], len(str(v))) for j, v in enumerate(row.values())]
    for i, width in enumerate(col_widths):
        # set column widths
        worksheet.set_column(i, i, width)
    table_options = {
        'name': 'LoadingSummary',
        'columns': [{'header': h} for h in headers]
    }
    worksheet.add_table(0, 0, len(rows), len(headers) - 1, table_options)
    workbook.close()
    response = flask.make_response(output.getvalue())
    response.headers.update({
        'Content-Disposition': 'attachment; filename="Loading Summary.xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    })
    return response


@app.post('/lock')
def lock():
    endpoint = flask.request.values.get('endpoint')
    log.debug(f'Got a request from session {flask.g.session_id} to lock {endpoint}')
    flask.g.db.lock_page(flask.g.session_id, endpoint)
    flask.g.db.lock_page(flask.g.session_id, f'{endpoint}_xlsx')
    return flask.redirect(flask.url_for('index'))


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
    for i, row in enumerate(rows, start=1):
        worksheet.write_row(i, 0, row.values(), text_wrap)
        worksheet.write_string(i, len(headers) - 1, notes.get(row['job_number'], ''), text_wrap)
        # find maximum column widths
        col_widths = [max(col_widths[j], len(str(v))) for j, v in enumerate(row.values())]
    for i, width in enumerate(col_widths):
        # set column widths
        worksheet.set_column(i, i, width)
    table_options = {
        'name': 'OpenSalesReport',
        'columns': [{'header': h} for h in headers]
    }
    worksheet.add_table(0, 0, len(rows), len(headers) - 1, table_options)
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


@app.get('/test')
@page_lock
def test():
    return 'OK'


@app.post('/unlock')
def unlock():
    endpoint = flask.request.values.get('endpoint')
    password = flask.request.values.get('password')
    log.debug(f'Got a request from session {flask.g.session_id} to unlock {endpoint}')
    if flask.g.db.check_page_password(endpoint, password):
        flask.g.db.unlock_page(flask.g.session_id, endpoint)
        flask.g.db.unlock_page(flask.g.session_id, f'{endpoint}_xlsx')
    return flask.redirect(flask.url_for(endpoint))


def main():
    waitress.serve(app, port=config.PORT, threads=8)


def handle_sigterm(_signal, _frame):
    sys.exit()


if __name__ == '__main__':
    with open(config.ERR_LOG, 'a') as f, contextlib.redirect_stderr(f):
        signal.signal(signal.SIGTERM, handle_sigterm)
        main()
