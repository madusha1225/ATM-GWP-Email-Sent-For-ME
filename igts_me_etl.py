import oracledb
import mysql.connector
from datetime import datetime

# -- CONFIG --------------------------------------------------------------------
ORACLE_CONFIG = {
    "user":     "GTMLIVE",
    "password": "ggTm_jE-c#S#%TR",
    "dsn":      "(DESCRIPTION=(ADDRESS_LIST=(ADDRESS=(PROTOCOL=TCP)(HOST=DBS1-SCAN.TAKAFUL.ODA)(PORT=1521)))(CONNECT_DATA=(SERVICE_NAME=ATMPROD.TAKAFUL.ODA)))"
}

MYSQL_CONFIG = {
    "host":     "localhost",
    "database": "bidataforme",
    "user":     "root",
    "password": "madusha1234",
}

DEPT_MAP = {
    "11": "Fire",        "12": "Marine Cargo",  "13": "Motor",
    "14": "Miscellaneous Accident", "15": "Engineering", "16": "Bond",
    "17": "Health",
    "18": "Liability",   "19": "Marine Hull",   "20": "Personal Accident",
    "21": "Workmen Compensation",               "22": "Life",
}

MANUAL_MONTH = 6
MANUAL_YEAR  = 2026

def get_month_year():
    now   = datetime.now()
    month = MANUAL_MONTH if MANUAL_MONTH else now.month
    year  = MANUAL_YEAR  if MANUAL_YEAR  else now.year
    return month, year


# -- SHARED JOIN TEMPLATE ------------------------------------------------------
BASE_JOIN = """
    FROM GTMLIVE.GI_GU_DH_DOC_HEADER h
    JOIN GTMLIVE.GI_GU_AD_AGENCYDTL ag
      ON  ag.POR_ORG_CODE    = h.POR_ORG_CODE
      AND ag.PDP_DEPT_CODE   = h.PDP_DEPT_CODE
      AND ag.PDT_DOCTYPE     = h.PDT_DOCTYPE
      AND ag.GDH_DOCUMENTNO  = h.GDH_DOCUMENTNO
      AND ag.GDH_RECORD_TYPE = h.GDH_RECORD_TYPE
      AND ag.GDH_YEAR        = h.GDH_YEAR
    JOIN GTMLIVE.PR_GN_PS_PARTY agent
      ON agent.PPS_PARTY_CODE = ag.PPS_PARTY_CODE
    JOIN GTMLIVE.PR_GN_PS_PARTY me
      ON me.PPS_PARTY_CODE = COALESCE(agent.PPS_REPORTING_TO,
                                      agent.PPS_PARTY_CODE)
    WHERE h.GDH_POSTING_TAG      = 'Y'
      AND h.GDH_CANCELLATION_TAG IS NULL
      AND h.PDT_DOCTYPE          IN ('P','E')
      AND h.POR_ORG_CODE         = '001001'
      AND h.GDH_RECORD_TYPE      = 'O'
"""


# -- EXTRACT FROM ORACLE -------------------------------------------------------
def extract_from_igts(month, year):
    print(f"[IGTS] Connecting to Oracle...")
    conn = oracledb.connect(
        user=ORACLE_CONFIG["user"],
        password=ORACLE_CONFIG["password"],
        dsn=ORACLE_CONFIG["dsn"]
    )
    cursor = conn.cursor()
    print(f"[IGTS] Connected. Extracting ME-wise GWP for {year}-{month:02d}...")

    month_data     = {}
    month_name_map = {}
    ytd_data       = {}

    # -- 1. Non-health departments MONTH ---------------------------------------
    cursor.execute(f"""
        SELECT
            me.PPS_PARTY_CODE,
            me.PPS_DESC,
            h.PDP_DEPT_CODE,
            SUM(h.GDH_GROSSPREMIUM * h.GDH_FCEXCHANGE_RATE),
            EXTRACT(MONTH FROM h.GDH_ISSUEDATE),
            EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)
        {BASE_JOIN}
          AND h.PDP_DEPT_CODE IN ('11','12','13','14','15',
                                   '16','18','19','20','21','22')
          AND EXTRACT(YEAR  FROM h.GDH_ISSUEDATE) = :yr
          AND EXTRACT(MONTH FROM h.GDH_ISSUEDATE) = :mn
        GROUP BY
            me.PPS_PARTY_CODE, me.PPS_DESC, h.PDP_DEPT_CODE,
            EXTRACT(MONTH FROM h.GDH_ISSUEDATE),
            EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)
    """, yr=year, mn=month)
    for r in cursor.fetchall():
        if r[3] is not None:
            key = (str(r[0]), str(r[2]), None)
            month_data[key]           = float(r[3])
            month_name_map[str(r[0])] = str(r[1]) if r[1] else str(r[0])

    # -- 2. Health Group (H0701) MONTH -----------------------------------------
    cursor.execute(f"""
        SELECT
            me.PPS_PARTY_CODE,
            me.PPS_DESC,
            SUM(h.GDH_GROSSPREMIUM * h.GDH_FCEXCHANGE_RATE),
            EXTRACT(MONTH FROM h.GDH_ISSUEDATE),
            EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)
        {BASE_JOIN}
          AND h.PDP_DEPT_CODE      = '17'
          AND h.PBC_BUSICLASS_CODE = 'H0701'
          AND EXTRACT(YEAR  FROM h.GDH_ISSUEDATE) = :yr
          AND EXTRACT(MONTH FROM h.GDH_ISSUEDATE) = :mn
        GROUP BY
            me.PPS_PARTY_CODE, me.PPS_DESC,
            EXTRACT(MONTH FROM h.GDH_ISSUEDATE),
            EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)
    """, yr=year, mn=month)
    for r in cursor.fetchall():
        if r[2] is not None:
            key = (str(r[0]), '17', 'Health - Group')
            month_data[key]           = float(r[2])
            month_name_map[str(r[0])] = str(r[1]) if r[1] else str(r[0])

    # -- 3. Health Retail (not H0701) MONTH ------------------------------------
    cursor.execute(f"""
        SELECT
            me.PPS_PARTY_CODE,
            me.PPS_DESC,
            SUM(h.GDH_GROSSPREMIUM * h.GDH_FCEXCHANGE_RATE),
            EXTRACT(MONTH FROM h.GDH_ISSUEDATE),
            EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)
        {BASE_JOIN}
          AND h.PDP_DEPT_CODE       = '17'
          AND (h.PBC_BUSICLASS_CODE != 'H0701'
               OR h.PBC_BUSICLASS_CODE IS NULL)
          AND EXTRACT(YEAR  FROM h.GDH_ISSUEDATE) = :yr
          AND EXTRACT(MONTH FROM h.GDH_ISSUEDATE) = :mn
        GROUP BY
            me.PPS_PARTY_CODE, me.PPS_DESC,
            EXTRACT(MONTH FROM h.GDH_ISSUEDATE),
            EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)
    """, yr=year, mn=month)
    for r in cursor.fetchall():
        if r[2] is not None:
            key = (str(r[0]), '17', 'Health - Retail')
            month_data[key]           = float(r[2])
            month_name_map[str(r[0])] = str(r[1]) if r[1] else str(r[0])

    # -- 4. Non-health departments YTD -----------------------------------------
    cursor.execute(f"""
        SELECT
            me.PPS_PARTY_CODE,
            h.PDP_DEPT_CODE,
            SUM(h.GDH_GROSSPREMIUM * h.GDH_FCEXCHANGE_RATE)
        {BASE_JOIN}
          AND h.PDP_DEPT_CODE IN ('11','12','13','14','15',
                                   '16','18','19','20','21','22')
          AND EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)  = :yr
          AND EXTRACT(MONTH FROM h.GDH_ISSUEDATE) <= :mn
        GROUP BY me.PPS_PARTY_CODE, h.PDP_DEPT_CODE
    """, yr=year, mn=month)
    for r in cursor.fetchall():
        if r[2] is not None:
            key = (str(r[0]), str(r[1]), None)
            ytd_data[key] = float(r[2])

    # -- 5. Health Group YTD ---------------------------------------------------
    cursor.execute(f"""
        SELECT
            me.PPS_PARTY_CODE,
            SUM(h.GDH_GROSSPREMIUM * h.GDH_FCEXCHANGE_RATE)
        {BASE_JOIN}
          AND h.PDP_DEPT_CODE      = '17'
          AND h.PBC_BUSICLASS_CODE = 'H0701'
          AND EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)  = :yr
          AND EXTRACT(MONTH FROM h.GDH_ISSUEDATE) <= :mn
        GROUP BY me.PPS_PARTY_CODE
    """, yr=year, mn=month)
    for r in cursor.fetchall():
        if r[1] is not None:
            key = (str(r[0]), '17', 'Health - Group')
            ytd_data[key] = float(r[1])

    # -- 6. Health Retail YTD --------------------------------------------------
    cursor.execute(f"""
        SELECT
            me.PPS_PARTY_CODE,
            SUM(h.GDH_GROSSPREMIUM * h.GDH_FCEXCHANGE_RATE)
        {BASE_JOIN}
          AND h.PDP_DEPT_CODE       = '17'
          AND (h.PBC_BUSICLASS_CODE != 'H0701'
               OR h.PBC_BUSICLASS_CODE IS NULL)
          AND EXTRACT(YEAR  FROM h.GDH_ISSUEDATE)  = :yr
          AND EXTRACT(MONTH FROM h.GDH_ISSUEDATE) <= :mn
        GROUP BY me.PPS_PARTY_CODE
    """, yr=year, mn=month)
    for r in cursor.fetchall():
        if r[1] is not None:
            key = (str(r[0]), '17', 'Health - Retail')
            ytd_data[key] = float(r[1])

    cursor.close()
    conn.close()
    print(f"[IGTS] {len(month_data)} month rows, {len(ytd_data)} YTD rows.")
    return month_data, ytd_data, month_name_map


# -- LOAD INTO MYSQL -----------------------------------------------------------
def load_to_mysql(month_data, ytd_data, month_name_map, month, year):
    print(f"[MySQL] Connecting...")
    conn   = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()

    # Add health_class column if missing
    try:
        cursor.execute("""
            ALTER TABLE bidataforme.igts_me_gwp_staging
            ADD COLUMN health_class VARCHAR(50) DEFAULT NULL
        """)
        conn.commit()
    except:
        pass

    # Drop & recreate unique key to include health_class
    try:
        cursor.execute("ALTER TABLE bidataforme.igts_me_gwp_staging DROP INDEX uq_me_igts")
        conn.commit()
    except:
        pass
    try:
        cursor.execute("""
            ALTER TABLE bidataforme.igts_me_gwp_staging
            ADD UNIQUE KEY uq_me_igts
                (me_code, dept_code, health_class, report_year, report_month)
        """)
        conn.commit()
    except:
        pass

    # Clear current month
    cursor.execute("""
        DELETE FROM bidataforme.igts_me_gwp_staging
        WHERE report_month = %s AND report_year = %s
    """, (month, year))
    conn.commit()
    print(f"[MySQL] Cleared rows for {year}-{month:02d}")

    all_keys = set(month_data.keys()) | set(ytd_data.keys())
    rows = []
    for (me_code, dept_code, health_class) in all_keys:
        month_gwp = month_data.get((me_code, dept_code, health_class), 0.0)
        ytd_gwp   = ytd_data.get((me_code, dept_code, health_class), 0.0)
        if dept_code == '17':
            dept_name = health_class  # "Health - Group" or "Health - Retail"
        else:
            dept_name = DEPT_MAP.get(dept_code, "Miscellaneous")
        me_name = month_name_map.get(me_code, me_code)
        rows.append((
            me_code, me_name, dept_code, dept_name, health_class,
            round(month_gwp, 2), round(ytd_gwp, 2), month, year,
        ))

    batch_size = 500
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        cursor.executemany("""
            INSERT INTO bidataforme.igts_me_gwp_staging
                (me_code, me_name, dept_code, dept_name, health_class,
                 month_gwp, ytd_gwp, report_month, report_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                me_name   = VALUES(me_name),
                dept_name = VALUES(dept_name),
                month_gwp = VALUES(month_gwp),
                ytd_gwp   = VALUES(ytd_gwp),
                loaded_at = CURRENT_TIMESTAMP
        """, batch)
        conn.commit()
        total += len(batch)
        print(f"[MySQL] Batch {i//batch_size+1}: {total}/{len(rows)} rows")

    cursor.close()
    conn.close()
    print(f"[MySQL] Done. {len(rows)} rows ? igts_me_gwp_staging.")


# -- MAIN ----------------------------------------------------------------------
if __name__ == "__main__":
    month, year = get_month_year()
    print(f"[ETL] Running ME-wise GWP for {year}-{month:02d}")
    month_data, ytd_data, month_name_map = extract_from_igts(month, year)
    load_to_mysql(month_data, ytd_data, month_name_map, month, year)
    print(f"[ETL] Complete.")