import pyodbc
import mysql.connector
from datetime import datetime

# -- CONFIG --------------------------------------------------------------------
MSSQL_CONFIG = {
    "server":   "172.18.73.21,58841",
    "database": "ATMProduction",
    "user":     "inube-sa",
    "password": 'fqyA\\S\\97"&H33jy',
    "driver":   "ODBC Driver 17 for SQL Server",
}

# !! Updated to bidataforme database !!
MYSQL_CONFIG = {
    "host":     "localhost",
    "database": "bidataforme",
    "user":     "root",
    "password": "madusha1234",
}

SYNC_FROM_DATE = "2026-01-01"


# -- EXTRACT FROM MS SQL -------------------------------------------------------
def extract_from_inube():
    print("[iNube] Connecting to MS SQL...")
    conn = pyodbc.connect(
        driver="{" + MSSQL_CONFIG['driver'] + "}",
        server=MSSQL_CONFIG['server'],
        database=MSSQL_CONFIG['database'],
        uid=MSSQL_CONFIG['user'],
        pwd=MSSQL_CONFIG['password']
    )
    cursor = conn.cursor()
    print(f"[iNube] Connected. Extracting from {SYNC_FROM_DATE}...")
    cursor.execute("""
        SELECT
            [Policy No],
            [Participant],
            [Business Registration No],
            [Agency],
            [Contact No],
            [Issue Date],
            [Comm Date],
            [Expiry Date],
            [Business Class],
            [Sum Covered],
            [Gross Contribution],
            [CESS],
            [Net Contribution],
            [Management Fee],
            [PolicyID],
            [ChannelDescription],
            [ReportingName],
            [ReportingCode],
            [agencycode],
            [channelCode],
            [participantCode]
        FROM RP.tblDWHProductionReport
        WHERE [Issue Date] >= ?
        ORDER BY [Issue Date]
    """, SYNC_FROM_DATE)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    rows = [tuple(row) for row in rows]
    print(f"[iNube] {len(rows)} records extracted.")
    return rows


# -- DEDUPLICATE ROWS ----------------------------------------------------------
def deduplicate_rows(rows):
    seen    = set()
    deduped = []
    skipped = 0
    for row in rows:
        policy_no          = str(row[0])[:40]
        issue_date         = str(row[5])
        gross_contribution = str(row[10])
        key = (policy_no, issue_date, gross_contribution)
        if key not in seen:
            seen.add(key)
            deduped.append(row)
        else:
            skipped += 1
    print(f"[Dedup] {skipped} duplicate(s) removed. {len(deduped)} unique records remain.")
    return deduped


# -- LOAD INTO MYSQL -----------------------------------------------------------
def load_to_mysql(rows):
    print("[MySQL] Connecting to bidataforme...")
    conn   = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()

    # Ensure table exists in bidataforme
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `bidataforme`.`tbldwhproductionreport` (
            `Policy No`               VARCHAR(40),
            `Participant`             VARCHAR(255),
            `Business Registration No` VARCHAR(255),
            `Agency`                  VARCHAR(255),
            `Contact No`              VARCHAR(255),
            `Issue Date`              DATE,
            `Comm Date`               DATE,
            `Expiry Date`             DATE,
            `Business Class`          VARCHAR(255),
            `Sum Covered`             DECIMAL(18,2),
            `Gross Contribution`      DECIMAL(18,2),
            `CESS`                    DECIMAL(18,2),
            `Net Contribution`        DECIMAL(18,2),
            `Management Fee`          DECIMAL(18,2),
            `PolicyID`                VARCHAR(255),
            `ChannelDescription`      VARCHAR(255),
            `ReportingName`           VARCHAR(255),
            `ReportingCode`           VARCHAR(50),
            `agencycode`              VARCHAR(50),
            `channelCode`             VARCHAR(50),
            `participantCode`         VARCHAR(50),
            UNIQUE KEY uq_policy (`Policy No`, `Issue Date`, `Gross Contribution`(20))
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci
    """)
    conn.commit()

    # Clear and reload
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    cursor.execute("TRUNCATE TABLE bidataforme.tbldwhproductionreport")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    print(f"[MySQL] Table cleared. Inserting {len(rows)} records...")

    # Insert in batches of 500
    batch_size = 500
    total      = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        cursor.executemany("""
            INSERT IGNORE INTO `bidataforme`.`tbldwhproductionreport` (
                `Policy No`, `Participant`, `Business Registration No`,
                `Agency`, `Contact No`, `Issue Date`, `Comm Date`,
                `Expiry Date`, `Business Class`, `Sum Covered`,
                `Gross Contribution`, `CESS`, `Net Contribution`,
                `Management Fee`, `PolicyID`, `ChannelDescription`,
                `ReportingName`, `ReportingCode`, `agencycode`,
                `channelCode`, `participantCode`
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, batch)
        conn.commit()
        total += len(batch)
        print(f"[MySQL] Inserted {total}/{len(rows)} records")

    cursor.execute("SELECT COUNT(*) FROM bidataforme.tbldwhproductionreport")
    count = cursor.fetchone()[0]
    print(f"[MySQL] Done. Total rows in bidataforme.tbldwhproductionreport: {count}")

    cursor.close()
    conn.close()


# -- MAIN ----------------------------------------------------------------------
if __name__ == "__main__":
    print(f"[Sync] Starting iNube sync at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    rows = extract_from_inube()
    rows = deduplicate_rows(rows)
    load_to_mysql(rows)
    print(f"[Sync] Complete at {datetime.now().strftime('%Y-%m-%d %H:%M')}")