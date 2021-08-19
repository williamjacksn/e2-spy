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
                od.status,
                od.grid_parent_job_number parent_job_number,
                od.part_number,
                od.part_description,
                coalesce(jcs.current_step, '') current_step,
                od.quantity_to_make,
                od.quantity_open,
                oh.customer_code,
                oh.customer_po_number customer_po,
                sj.sales_amount,
                coalesce(format(sj.order_date, 'yyyy-MM-dd'), '') order_date,
                coalesce(format(sj.projected_ship_date, 'yyyy-MM-dd'), '') ship_by_date,
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
            and od.status in ('hold', 'in process', 'released')
            order by od.priority
        '''
        return self.q(sql)
