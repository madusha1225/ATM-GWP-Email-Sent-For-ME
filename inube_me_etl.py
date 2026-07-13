import mysql.connector
from datetime import datetime

# -- CONFIG --------------------------------------------------------------------
MYSQL_CONFIG = {
    "host":     "localhost",
    "database": "bidataforme",
    "user":     "root",
    "password": "madusha1234",
}

MANUAL_MONTH = 6
MANUAL_YEAR  = 2026

def get_month_year():
    now   = datetime.now()
    month = MANUAL_MONTH if MANUAL_MONTH else now.month
    year  = MANUAL_YEAR  if MANUAL_YEAR  else now.year
    return month, year


# -- MAIN ETL ------------------------------------------------------------------
def process_inube_me_health(month, year):
    print(f"[iNube ME] Connecting to MySQL (bidataforme)...")
    conn   = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()

    # Ensure table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `bidataforme`.`inube_me_health_staging` (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            me_code        VARCHAR(50),
            me_name        VARCHAR(100),
            health_class   VARCHAR(50),
            month_gwp      DECIMAL(18,2) DEFAULT 0,
            ytd_gwp        DECIMAL(18,2) DEFAULT 0,
            report_month   INT,
            report_year    INT,
            loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                           ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_inube_me (me_code, health_class,
                                    report_year, report_month)
        )
    """)
    conn.commit()

    # Clear current month
    cursor.execute("""
        DELETE FROM bidataforme.inube_me_health_staging
        WHERE report_month = %s AND report_year = %s
    """, (month, year))
    conn.commit()
    print(f"[iNube ME] Cleared rows for {year}-{month:02d}")

    # -- Month GWP
    # GSHP / GSHP SME / GSHP* ? Health - Group
    # Everything else          ? Health - Retail
    cursor.execute("""
        SELECT
            p.ReportingCode                                      AS me_code,
            COALESCE(m.me_name, p.ReportingName,
                     p.ReportingCode)                            AS me_name,
            CASE
                WHEN TRIM(p.`Business Class`) LIKE 'GSHP%'
                THEN 'Health - Group'
                ELSE 'Health - Retail'
            END                                                  AS health_class,
            SUM(p.`Gross Contribution`)                          AS month_gwp
        FROM bidataforme.tbldwhproductionreport p
        LEFT JOIN bidataforme.me_master m
               ON m.me_target_code = p.ReportingCode
        WHERE MONTH(p.`Issue Date`) = %s
          AND YEAR(p.`Issue Date`)  = %s
          AND p.ReportingCode IS NOT NULL
          AND p.ReportingCode != ''
        GROUP BY
            p.ReportingCode,
            COALESCE(m.me_name, p.ReportingName, p.ReportingCode),
            CASE
                WHEN TRIM(p.`Business Class`) LIKE 'GSHP%'
                THEN 'Health - Group'
                ELSE 'Health - Retail'
            END
    """, (month, year))
    month_rows = cursor.fetchall()

    # -- YTD GWP
    cursor.execute("""
        SELECT
            p.ReportingCode                                      AS me_code,
            CASE
                WHEN TRIM(p.`Business Class`) = 'GSHP'
                THEN 'Health - Group'
                ELSE 'Health - Retail'
            END                                                  AS health_class,
            SUM(p.`Gross Contribution`)                          AS ytd_gwp
        FROM bidataforme.tbldwhproductionreport p
        WHERE YEAR(p.`Issue Date`)  = %s
          AND MONTH(p.`Issue Date`) <= %s
          AND p.ReportingCode IS NOT NULL
          AND p.ReportingCode != ''
        GROUP BY
            p.ReportingCode,
            CASE
                WHEN TRIM(p.`Business Class`) = 'GSHP'
                THEN 'Health - Group'
                ELSE 'Health - Retail'
            END
    """, (year, month))
    ytd_rows = cursor.fetchall()

    # Build dicts
    month_data     = {}
    month_name_map = {}
    for r in month_rows:
        key = (str(r[0]), str(r[2]))
        month_data[key]           = float(r[3]) if r[3] else 0.0
        month_name_map[str(r[0])] = str(r[1])

    ytd_data = {}
    for r in ytd_rows:
        key = (str(r[0]), str(r[1]))
        ytd_data[key] = float(r[2]) if r[2] else 0.0

    all_keys = set(month_data.keys()) | set(ytd_data.keys())
    rows = []
    for (me_code, health_class) in all_keys:
        month_gwp = month_data.get((me_code, health_class), 0.0)
        ytd_gwp   = ytd_data.get((me_code, health_class), 0.0)
        me_name   = month_name_map.get(me_code, me_code)
        rows.append((
            me_code, me_name, health_class,
            round(month_gwp, 2), round(ytd_gwp, 2),
            month, year,
        ))

    if rows:
        cursor.executemany("""
            INSERT INTO bidataforme.inube_me_health_staging
                (me_code, me_name, health_class,
                 month_gwp, ytd_gwp, report_month, report_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                me_name   = VALUES(me_name),
                month_gwp = VALUES(month_gwp),
                ytd_gwp   = VALUES(ytd_gwp),
                loaded_at = CURRENT_TIMESTAMP
        """, rows)
        conn.commit()

    cursor.close()
    conn.close()
    print(f"[iNube ME] Done. {len(rows)} rows ? inube_me_health_staging.")
    return len(rows)


if __name__ == "__main__":
    month, year = get_month_year()
    print(f"[iNube ME ETL] Running for {year}-{month:02d}")
    process_inube_me_health(month, year)
    print(f"[iNube ME ETL] Complete.")