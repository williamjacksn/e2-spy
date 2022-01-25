import contextlib
import datetime
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

    def action_summary(self, start_date: datetime.date, end_date: datetime.date, users: list[str]):
        sql = '''
            select
                a.action_code, a.action_id, a.completed_date,
                datediff(day, a.entered_date, a.completed_date) days_to_complete, a.description, a.entered_date,
                a.followup_by_user_code, a.followup_completed, a.notes, o.order_number, a.status,
                (datediff(day, a.entered_date, a.completed_date) + 1) -
                (datediff(wk, a.entered_date, a.completed_date) * 2) -
                (case when datename(dw, a.entered_date) = 'Sunday' then 1 else 0 end) -
                (case when datename(dw, a.completed_date) = 'Saturday' then 1 else 0 end) business_days_to_complete
            from action a
            left join order_header o on o.order_header_id = a.order_header_id
            where a.order_header_id is not null
            and a.entered_date between %s and %s
        '''
        if users:
            sql = f'''{sql}
            and a.followup_by_user_code in %s
            '''
        params = (
            start_date,
            end_date + datetime.timedelta(days=1),
            users,
        )
        return self.q(sql, params)

    def closed_jobs(self):
        sql = '''
            select
                oh.customer_code, oh.customer_po_number, od.date_closed, od.job_number, oh.order_number,
                od.part_description, od.part_number
            from order_detail od
            left join order_header oh on oh.order_header_id = od.order_header_id
            where oh.company_code = 'spmtech'
            and od.status = 'closed'
            order by od.date_closed desc
        '''
        return self.q(sql)

    def days_since_last_activity(self):
        sql = '''
            select
                c.job_number, c.part_number, c.part_description, c.current_step,
                coalesce(ns.work_center, ns.vendor_code, 'LAST STEP') next_step, c.actual_start_date, c.actual_end_date,
                datediff(
                    day, (select max(v) from (values (c.actual_start_date), (c.actual_end_date)) as value(v)),
                    sysdatetime()
                ) as days_since_last_activity
            from (
                select
                    job_number, part_number, part_description, coalesce(work_center, vendor_code) current_step,
                    actual_start_date, actual_end_date, item_number,
                    row_number() over (partition by job_number order by item_number) z
                from schedule_detail
                where schedule_header_id = 50
                and step_status in ('current', 'pending')
            ) c
            left join schedule_detail ns on
                ns.schedule_header_id = 50 and ns.job_number = c.job_number and ns.item_number = c.item_number + 1
            where z = 1
            order by days_since_last_activity desc
        '''
        return self.q(sql)

    def get_followup_user_code_list(self) -> list[str]:
        sql = '''
            select distinct followup_by_user_code
            from action
            where len(followup_by_user_code) > 0
            order by followup_by_user_code
        '''
        return [row.get('followup_by_user_code') for row in self.q(sql)]

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
                sd.department_name, sd.job_number, sd.work_center, sd.priority, sd.part_number, sd.part_description,
                sd.quantity_to_make, sd.quantity_open, sd.scheduled_start_date start_date,
                sd.scheduled_end_date end_date, sd.due_date,
                coalesce(ns.work_center, ns.vendor_code, 'LAST STEP') next_step
            from (
                select
                    department_name, due_date, item_number, job_number, part_description, part_number, priority,
                    quantity_open, quantity_to_make, schedule_job_id, scheduled_end_date, scheduled_start_date,
                    step_number, work_center, row_number() over (partition by job_number order by item_number) z
                from schedule_detail
                where schedule_header_id = 50
                and department_name in %s
                and scheduled_start_date < %s
                and step_status in ('current', 'pending')) sd
            left join schedule_detail ns
                on ns.schedule_job_id = sd.schedule_job_id and ns.item_number = sd.item_number + 1
            where z = 1
            order by priority
        '''
        params = (
            departments,
            pymssql.datetime.date.today() + pymssql.datetime.timedelta(days=1)
        )
        return self.q(sql, params)

    def gl_accounts_list(self):
        sql = '''
            select gl_account, description, gl_group_code, account_type
            from gl_account
            where company_code = 'spmtech'
        '''
        return self.q(sql)

    def income_statement(self):
        sql = '''
            select a.gl_account_id, a.active, b.period_number, b.amount, a.description, a.gl_group_code, a.account_type
            from gl_balance b
            join gl_account a on a.gl_account_id = b.gl_account_id
            where b.period_number = '202201'
            order by a.gl_account
        '''
        return self.q(sql)
    
    def job_performance(self, start_date: datetime.date, end_date: datetime.date):
        sql = '''
            select
                cast(date_closed as date) date_closed, job_number, part_description, part_number,
                cast(
                    case
                        when total_estimated_hours > 0 then total_actual_hours / total_estimated_hours * 100
                        else 0
                    end
                    as int) performance, total_actual_hours, total_estimated_hours
            from order_detail
            where company_code = 'spmtech'
            and status = 'closed'
            and cast(date_closed as date) between %s and %s
            order by date_closed desc
        '''
        params = (
            start_date,
            end_date,
        )
        return self.q(sql, params)

    def open_sales_report(self):
        sql = '''
            with jpo as (
                select
                    j.job_number,
                    string_agg(p.vendor_name, char(10)) within group (order by p.po_number) vendor,
                    string_agg(p.po_number, char(10)) within group (order by p.po_number) vendor_po,
                    string_agg(format(p.po_date, 'yyyy-MM-dd'), char(10)) within group (order by p.po_number) as po_date,
                    string_agg(format(p.due_date, 'yyyy-MM-dd'), char(10)) within group (order by p.po_number) po_due_date
                from (
                    select distinct m.job_number, m.po_header_id
                    from order_material m
                    where m.po_header_id is not null
                ) j
                left join po_header p on p.po_header_id = j.po_header_id
                group by j.job_number
            ),
            jcs as (
                select job_number, current_step
                from (
                    select
                        job_number, coalesce(work_center, vendor_code) current_step,
                        row_number() over (partition by job_number order by item_number) z
                    from schedule_detail
                    where schedule_header_id = 50
                    and step_status in ('current', 'pending')
                ) c
                where z = 1
            )
            select
                od.job_number,
                od.priority,
                oh.order_type,
                od.status,
                od.grid_parent_job_number parent_job_number,
                od.part_number,
                od.part_description,
                coalesce(jcs.current_step, '') current_step,
                od.quantity_to_make,
                od.quantity_open,
                oh.customer_code,
                oh.customer_po_number customer_po,
                coalesce(sj.sales_amount, od.gross_amount) sales_amount,
                coalesce(format(oh.order_date, 'yyyy-MM-dd'), '') order_date,
                coalesce(format(od.projected_ship_date, 'yyyy-MM-dd'), '') ship_by_date,
                coalesce(format(sj.scheduled_end_date, 'yyyy-MM-dd'), '') scheduled_end_date,
                jpo.vendor,
                jpo.vendor_po,
                jpo.po_date,
                jpo.po_due_date
            from order_detail od
            left join order_header oh on oh.order_header_id = od.order_header_id
            left join jcs on jcs.job_number = od.job_number
            left join schedule_job sj on sj.order_detail_id = od.order_detail_id and sj.schedule_header_id = 50
            left join jpo on jpo.job_number = od.job_number
            where od.company_code = 'spmtech'
            and od.status in ('firm', 'hold', 'in process', 'released')
            order by od.priority
        '''
        return self.q(sql)
