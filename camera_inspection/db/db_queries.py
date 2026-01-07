import psycopg2
from config.db_config import TABLE,DB
from datetime import datetime

def save_record(data, status, img_bytes):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {TABLE}
        (employee_id, work_order, charge_no, serial_no,
         part_no, unique_no, status, time, image)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """,
        (
            data["emp"],
            data["wo"],
            data["charge"],
            data["serial"],
            data["part"],
            data["unique"],
            status,
            datetime.now(),
            psycopg2.Binary(img_bytes),
        ),
    )
    conn.commit()
    cur.close()
    conn.close()










def fetch_report(from_dt, to_dt, status, unique_no=None, limit=None, offset=None):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    q = f"""
        SELECT employee_id, work_order, charge_no,
               serial_no, part_no, unique_no,
               image, status, time
        FROM {TABLE}
        WHERE time BETWEEN %s AND %s
    """
    params = [from_dt, to_dt]

    if status != "ALL":
        q += " AND status=%s"
        params.append(status)

    if unique_no:
        q += " AND unique_no ILIKE %s"
        params.append(f"%{unique_no}%")

    q += " ORDER BY time DESC"

    if limit is not None:
        q += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    cur.execute(q, params)
    rows = cur.fetchall()

    # total count
    count_q = f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE time BETWEEN %s AND %s
    """
    count_params = [from_dt, to_dt]

    if status != "ALL":
        count_q += " AND status=%s"
        count_params.append(status)

    if unique_no:
        count_q += " AND unique_no ILIKE %s"
        count_params.append(f"%{unique_no}%")

    cur.execute(count_q, count_params)
    total = cur.fetchone()[0]

    cur.close()
    conn.close()
    return rows, total






def get_home_counts():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # Total counts
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status='OK') AS ok_count,
            COUNT(*) FILTER (WHERE status='NOT_OK') AS not_ok_count
        FROM {TABLE}
    """
    )
    total, ok_cnt, not_ok_cnt = cur.fetchone()

    # Today count
    today_start = datetime.combine(datetime.today().date(), time.min)
    today_end = datetime.combine(datetime.today().date(), time.max)

    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE time BETWEEN %s AND %s
    """,
        (today_start, today_end),
    )
    today_cnt = cur.fetchone()[0]

    cur.close()
    conn.close()

    return (total or 0, ok_cnt or 0, not_ok_cnt or 0, today_cnt or 0)




def unique_exists(unique_no):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(f"SELECT 1 FROM {TABLE} WHERE unique_no=%s LIMIT 1", (unique_no,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists
