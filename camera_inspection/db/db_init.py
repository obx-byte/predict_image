import psycopg2
from config.db_config import DB








def init_db():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id SERIAL PRIMARY KEY,
            employee_id TEXT,
            work_order TEXT,
            charge_no TEXT,
            serial_no TEXT,
            part_no TEXT,
            unique_no TEXT,
            status TEXT,
            time TIMESTAMP,
            image BYTEA
        )
    """
    )
    conn.commit()
    cur.close()
    conn.close()
