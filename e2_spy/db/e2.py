import contextlib
import pymssql


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

    def get_loading_summary(self, departments: list[str]):
        sql = '''
            select
                sd.department_name,
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
            left join schedule_detail ns
                on ns.schedule_job_id = sd.schedule_job_id and ns.item_number = sd.item_number + 1
            where sd.department_name in %s
            and sd.step_status in ('Current', 'Pending')
            and sd.scheduled_start_date < %s
            order by sd.due_date
        '''
        params = (
            departments,
            pymssql.datetime.date.today() + pymssql.datetime.timedelta(days=1)
        )
        return self.q(sql, params)
