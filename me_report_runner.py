import subprocess
import mysql.connector
import calendar
from datetime import datetime, timedelta
import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# -- CONFIG --------------------------------------------------------------------
SCRIPTS_DIR = r"C:\Users\madusha.lakmina\Videos\BI Daily ME New System V2 (Data get by ME Vise)"

# !! SET TO False WHEN READY TO SEND TO REAL MEs !!
TEST_MODE = True   # When True all emails go ONLY to CC_EMAIL for testing

# !! TO SEND TO ONE SPECIFIC ME ONLY:
# Set SINGLE_ME_CODE = 'ME code here'  e.g. '310001000004'
# Set SINGLE_ME_CODE = None  to send to ALL MEs
SINGLE_ME_CODE = None

MYSQL_CONFIG = {
    "host":     "localhost",
    "database": "bidataforme",
    "user":     "root",
    "password": "madusha1234",
}

COMPANY_NAME = "Amãna Takaful (Maldives) PLC"
CURRENCY     = "MVR"
SIGNOFF_NAME = "Madusha Lakmina"
SIGNOFF_ROLE = "Support Agent - IT"

SMTP_SERVER  = "smtp.office365.com"
SMTP_PORT    = 587
SMTP_USER    = "bi@takaful.mv"
SMTP_PASS    = "G%084887817994or"
CC_EMAIL     = "bi@takaful.mv"
# CC_EMAIL     = "sarada.jayalath@takaful.mv"


# -- GET REPORT PERIOD ---------------------------------------------------------
def get_report_period():
    conn   = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            manual_month,
            manual_year,
            IF(manual_month = 5, MONTH(CURDATE()), manual_month),
            IF(manual_year  = 2026, YEAR(CURDATE()),  manual_year)
        FROM bidataforme.report_control WHERE id = 1
    """)
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    manual_month  = row[0]
    rpt_month     = row[2]
    rpt_year      = row[3]
    month_name    = calendar.month_name[rpt_month]
    report_period = f"{month_name} {rpt_year}"
    yesterday     = datetime.now() - timedelta(days=1)
    as_of_str     = (yesterday.strftime("%d %B %Y")
                     if manual_month == 0
                     else f"{month_name} {rpt_year}")
    return rpt_month, rpt_year, month_name, report_period, as_of_str


# -- STEP 1: RUN SYNC SCRIPTS --------------------------------------------------
def run_sync_scripts():
    scripts = ["inube_sync.py", "igts_me_etl.py", "inube_me_etl.py"]
    for script in scripts:
        full_path = os.path.join(SCRIPTS_DIR, script)
        print(f"[Runner] Running {script}...")
        timeout = 600 if script == "inube_sync.py" else 300
        result = subprocess.run(
            [sys.executable, full_path],
            capture_output=True, text=True,
            timeout=timeout
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"[Runner] WARNING: {script} failed:\n{result.stderr}")
        else:
            print(f"[Runner] {script} completed OK.")


# -- STEP 2: GET ME LIST -------------------------------------------------------
def fetch_me_list(rpt_month, rpt_year):
    conn   = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor(dictionary=True)

    if SINGLE_ME_CODE:
        # Send to ONE specific ME only
        cursor.execute("""
            SELECT me_target_code AS me_code, me_name, email
            FROM bidataforme.me_master
            WHERE me_target_code = %s
              AND email IS NOT NULL AND email != ''
              AND (is_active IS NULL OR is_active = 1)
        """, (SINGLE_ME_CODE,))
    else:
        # Send to ALL active MEs
        cursor.execute("""
            SELECT me_target_code AS me_code, me_name, email
            FROM bidataforme.me_master
            WHERE email IS NOT NULL AND email != ''
              AND (is_active IS NULL OR is_active = 1)
            ORDER BY me_name
        """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    print(f"[ME List] {len(rows)} ME(s) found.")
    return rows


# -- STEP 3: FETCH DATA FOR ONE ME ---------------------------------------------
def fetch_me_data(me_code, rpt_month, rpt_year):
    conn   = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            class_name,
            dept_code,
            month_gwp,
            ytd_gwp,
            month_budget,
            ytd_budget
        FROM bidataforme.v_me_gwp_report
        WHERE me_code      = %s
          AND report_month = %s
          AND report_year  = %s
        ORDER BY
            CASE dept_code
                WHEN '11' THEN 1  WHEN '12' THEN 2
                WHEN '13' THEN 3  WHEN '14' THEN 4
                WHEN '15' THEN 5  WHEN '16' THEN 6
                WHEN '18' THEN 7  WHEN '19' THEN 8
                WHEN '20' THEN 9  WHEN '21' THEN 10
                WHEN '22' THEN 11 ELSE 12
            END,
            class_name
    """, (me_code, rpt_month, rpt_year))
    all_rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Separate into groups
    health_rows  = []  # Health - Group, Health - Retail
    life_rows    = []  # Life (dept 22)
    general_rows = []  # All other departments

    for r in all_rows:
        row = {
            "class_name":   r["class_name"],
            "dept_code":    r["dept_code"],
            "month_gwp":    float(r["month_gwp"]    or 0),
            "ytd_gwp":      float(r["ytd_gwp"]      or 0),
            "month_budget": float(r["month_budget"] or 0),
            "ytd_budget":   float(r["ytd_budget"]   or 0),
        }
        if r["dept_code"] == "17":
            health_rows.append(row)
        elif r["dept_code"] == "22":
            life_rows.append(row)
        else:
            general_rows.append(row)

    return {
        "health":  health_rows,
        "life":    life_rows,
        "general": general_rows,
    }


# -- STEP 4: BUILD HTML --------------------------------------------------------
def build_me_html(me_name, data, report_period, as_of_str, month_name, rpt_year):

    health_rows  = data["health"]
    life_rows    = data["life"]
    general_rows = data["general"]
    all_rows     = health_rows + life_rows + general_rows

    # Grand totals
    tot_month_gwp  = sum(r["month_gwp"]    for r in all_rows)
    tot_ytd_gwp    = sum(r["ytd_gwp"]      for r in all_rows)
    tot_month_budg = sum(r["month_budget"] for r in all_rows)
    tot_ytd_budg   = sum(r["ytd_budget"]   for r in all_rows)

    def fmt(v):
        if v is None: return "&#8212;"
        return f"{v:,.2f}"

    def fmt_m(v):
        if v is None: return "&#8212;"
        if abs(v) >= 1_000_000: return f"{v/1_000_000:.2f}M"
        if abs(v) >= 1_000:     return f"{v/1_000:.1f}K"
        return f"{v:,.0f}"

    def pct(a, b):
        if not b or b == 0: return None
        return (a / b) * 100

    def ach_badge(val):
        if val is None:
            return '<span style="display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;background:#f3f4f6;color:#9ca3af;font-weight:500;">N/A</span>'
        p = f"{val:.1f}%"
        if val >= 100:
            return f'<span style="display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;background:#dcfce7;color:#15803d;">{p}</span>'
        if val >= 75:
            return f'<span style="display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;background:#fef9c3;color:#92400e;">{p}</span>'
        if val >= 50:
            return f'<span style="display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;background:#ffedd5;color:#c2410c;">{p}</span>'
        return f'<span style="display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;background:#fee2e2;color:#b91c1c;">{p}</span>'

    def progress_bar(val):
        if val is None: return ""
        width = min(val, 100)
        if val >= 100:  color = "#16a34a"
        elif val >= 75: color = "#ca8a04"
        elif val >= 50: color = "#ea580c"
        else:           color = "#dc2626"
        return (
            f'<div style="background:#e5e7eb;border-radius:4px;height:4px;width:70px;'
            f'display:inline-block;vertical-align:middle;margin-left:5px;">'
            f'<div style="background:{color};width:{width:.1f}%;height:4px;border-radius:4px;"></div>'
            f'</div>'
        )

    def ach_border(val):
        if val is None:  return "#2e9954"
        if val >= 100:   return "#16a34a"
        if val >= 75:    return "#ca8a04"
        if val >= 50:    return "#ea580c"
        return "#dc2626"

    apr_ach = pct(tot_month_gwp, tot_month_budg)
    ytd_ach = pct(tot_ytd_gwp,  tot_ytd_budg)

    CELL = "1px solid #b7e4c7"

    # KPI card
    def kpi_card(label, value, sub, border_color, ach_pct=None):
        bar = ""
        if ach_pct is not None:
            bar_w = min(ach_pct, 100)
            bar = (
                f'<div style="margin-top:8px;background:#e5e7eb;border-radius:4px;height:5px;">'
                f'<div style="background:{border_color};width:{bar_w:.1f}%;height:5px;border-radius:4px;"></div>'
                f'</div>'
            )
        return (
            f'<td width="25%" valign="top" style="padding:0 6px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>'
            f'<td style="background:#ffffff;border-radius:8px;padding:16px 18px;'
            f'border:1px solid #e5e7eb;border-top:3px solid {border_color};">'
            f'<div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;'
            f'color:#6b7280;font-weight:600;margin-bottom:6px;">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:#111827;font-family:monospace;">{value}</div>'
            f'<div style="font-size:11px;color:#9ca3af;margin-top:3px;">{sub}</div>'
            f'{bar}</td></tr></table></td>'
        )

    kpi_html = (
        f'<table width="100%" cellpadding="0" cellspacing="6"><tr>'
        f'{kpi_card(f"{month_name} GWP", fmt_m(tot_month_gwp), f"Budget: {CURRENCY} {fmt_m(tot_month_budg)}", "#2e9954")}'
        f'{kpi_card(f"{month_name} Achievement", f"{apr_ach:.1f}%" if apr_ach else "N/A", f"of {month_name} budget", ach_border(apr_ach), apr_ach)}'
        f'{kpi_card("YTD GWP", fmt_m(tot_ytd_gwp), f"Budget: {CURRENCY} {fmt_m(tot_ytd_budg)}", "#0d9e55")}'
        f'{kpi_card("YTD Achievement", f"{ytd_ach:.1f}%" if ytd_ach else "N/A", "of YTD budget", ach_border(ytd_ach), ytd_ach)}'
        f'</tr></table>'
    )

    # Section header (same style as old report)
    def group_header(label):
        return (
            f'<tr bgcolor="#f0faf4" style="background:#f0faf4;">'
            f'<td colspan="7" style="padding:8px 12px 7px 16px;font-size:10px;color:#2e9954;'
            f'letter-spacing:2px;text-transform:uppercase;font-weight:700;'
            f'border-top:2px solid #b7e4c7;border-bottom:1px solid #b7e4c7;">{label}</td>'
            f'</tr>'
        )

    # Data row
    def data_row(name, month_gwp, month_budg, ytd_gwp, ytd_budg, alt=False):
        m_a   = pct(month_gwp, month_budg) if month_budg else None
        y_a   = pct(ytd_gwp,  ytd_budg)   if ytd_budg   else None
        bg    = "#fafafa" if alt else "#ffffff"
        bar_m = progress_bar(m_a) if m_a is not None else ""
        bar_y = progress_bar(y_a) if y_a is not None else ""
        m_b   = fmt(month_budg) if month_budg else "&#8212;"
        y_b   = fmt(ytd_budg)   if ytd_budg   else "&#8212;"
        return (
            f'<tr bgcolor="{bg}" style="background:{bg};">'
            f'<td style="padding:10px 12px 10px 16px;font-size:13px;color:#1f2937;font-weight:500;border:{CELL};">{name}</td>'
            f'<td style="padding:10px 12px;text-align:right;font-family:monospace;font-size:12px;color:#374151;border:{CELL};">{fmt(month_gwp)}</td>'
            f'<td style="padding:10px 12px;text-align:right;font-family:monospace;font-size:12px;color:#6b7280;border:{CELL};">{m_b}</td>'
            f'<td style="padding:10px 12px;text-align:right;white-space:nowrap;border:{CELL};">{ach_badge(m_a)}{bar_m}</td>'
            f'<td style="padding:10px 12px;text-align:right;font-family:monospace;font-size:12px;color:#374151;border:{CELL};">{fmt(ytd_gwp)}</td>'
            f'<td style="padding:10px 12px;text-align:right;font-family:monospace;font-size:12px;color:#6b7280;border:{CELL};">{y_b}</td>'
            f'<td style="padding:10px 16px 10px 12px;text-align:right;white-space:nowrap;border:{CELL};">{ach_badge(y_a)}{bar_y}</td>'
            f'</tr>'
        )

    # Build Medical section (Health - Group + Health - Retail)
    medical_html = ""
    if health_rows:
        medical_html = group_header("Medical")
        for i, r in enumerate(health_rows):
            medical_html += data_row(
                r["class_name"],
                r["month_gwp"], r["month_budget"],
                r["ytd_gwp"],   r["ytd_budget"],
                alt=(i % 2 == 1)
            )

    # Build Life section
    life_html = ""
    if life_rows:
        life_html = group_header("Life")
        for i, r in enumerate(life_rows):
            life_html += data_row(
                r["class_name"],
                r["month_gwp"], r["month_budget"],
                r["ytd_gwp"],   r["ytd_budget"],
                alt=(i % 2 == 1)
            )

    # Build General Insurance section
    general_html = ""
    if general_rows:
        general_html = group_header("General Insurance")
        for i, r in enumerate(general_rows):
            general_html += data_row(
                r["class_name"],
                r["month_gwp"], r["month_budget"],
                r["ytd_gwp"],   r["ytd_budget"],
                alt=(i % 2 == 1)
            )

    table_body = medical_html + life_html + general_html

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>GWP Report - {me_name}</title>
</head>
<body style="margin:0;padding:28px 12px;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;color:#1a1a1a;">
<div style="max-width:900px;margin:0 auto;">

  <!-- HEADER -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#1e7d42;border-radius:10px 10px 0 0;border-collapse:collapse;">
    <tr><td style="padding:18px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>
        <td valign="middle">
          <div style="font-size:9px;letter-spacing:1.5px;color:#bbf7d0;text-transform:uppercase;">{COMPANY_NAME.upper()}</div>
          <div style="font-size:20px;font-weight:bold;color:#ffffff;margin-top:4px;">GWP Performance &ndash; {me_name}</div>
          <div style="font-size:11px;color:#d1fae5;margin-top:4px;">As of <b>{as_of_str}</b> &nbsp;|&nbsp; Period: <b>{report_period}</b></div>
        </td>
        <td valign="middle" align="right">
          <table cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>
            <td style="background:#2e9954;padding:8px 14px;border-radius:6px;text-align:center;">
              <div style="font-size:8px;color:#bbf7d0;letter-spacing:1px;">CURRENCY</div>
              <div style="font-size:14px;font-weight:bold;color:#ffffff;font-family:monospace;">{CURRENCY}</div>
            </td>
          </tr></table>
        </td>
      </tr></table>
    </td></tr>
  </table>

  <!-- LEGEND -->
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#166534;border-collapse:collapse;">
    <tr><td style="padding:9px 32px;">
      <table cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>
        <td style="padding-right:24px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;margin-right:5px;vertical-align:middle;"></span><span style="font-size:11px;color:#a8dbb9;">&ge;100% <b style="color:#d4f0de;">On Track</b></span></td>
        <td style="padding-right:24px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#facc15;margin-right:5px;vertical-align:middle;"></span><span style="font-size:11px;color:#a8dbb9;">75&ndash;99% <b style="color:#d4f0de;">Watch</b></span></td>
        <td style="padding-right:24px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#fb923c;margin-right:5px;vertical-align:middle;"></span><span style="font-size:11px;color:#a8dbb9;">50&ndash;74% <b style="color:#d4f0de;">Caution</b></span></td>
        <td><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#f87171;margin-right:5px;vertical-align:middle;"></span><span style="font-size:11px;color:#a8dbb9;">&lt;50% <b style="color:#d4f0de;">Attention</b></span></td>
      </tr></table>
    </td></tr>
  </table>

  <!-- MAIN CARD -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#ffffff;border-radius:0 0 12px 12px;border-collapse:collapse;">
    <tr><td style="padding:28px 32px 32px;">

      <div style="margin-bottom:28px;">{kpi_html}</div>

      <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#94a3b8;
                  font-weight:700;padding-bottom:10px;border-bottom:2px solid #b7e4c7;margin-bottom:0;">
        Product Performance Breakdown
      </div>

      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse;border:2px solid #b7e4c7;">
        <thead>
          <tr bgcolor="#f0faf4" style="background:#f0faf4;">
            <th style="padding:10px 12px 10px 16px;text-align:left;color:#166534;font-size:10px;font-weight:700;border-bottom:2px solid #b7e4c7;border-right:{CELL};">Business Class</th>
            <th style="padding:10px 10px;text-align:right;color:#166534;font-size:10px;font-weight:700;border-bottom:2px solid #b7e4c7;border-right:{CELL};">{month_name} GWP</th>
            <th style="padding:10px 10px;text-align:right;color:#166534;font-size:10px;font-weight:700;border-bottom:2px solid #b7e4c7;border-right:{CELL};">{month_name} Budget</th>
            <th style="padding:10px 10px;text-align:right;color:#166534;font-size:10px;font-weight:700;border-bottom:2px solid #b7e4c7;border-right:{CELL};">Month Ach%</th>
            <th style="padding:10px 10px;text-align:right;color:#166534;font-size:10px;font-weight:700;border-bottom:2px solid #b7e4c7;border-right:{CELL};">YTD GWP</th>
            <th style="padding:10px 10px;text-align:right;color:#166534;font-size:10px;font-weight:700;border-bottom:2px solid #b7e4c7;border-right:{CELL};">YTD Budget</th>
            <th style="padding:10px 14px 10px 10px;text-align:right;color:#166534;font-size:10px;font-weight:700;border-bottom:2px solid #b7e4c7;">YTD Ach%</th>
          </tr>
        </thead>
        <tbody>{table_body}</tbody>
        <tfoot>
          <tr bgcolor="#1a6b3a" style="background:#1a6b3a;">
            <td style="padding:12px 12px 12px 16px;color:#e2f5ea;font-size:12px;font-weight:700;border-top:2px solid #b7e4c7;">TOTAL</td>
            <td style="padding:12px 10px;text-align:right;color:#e2f5ea;font-family:monospace;font-size:11.5px;font-weight:600;border-top:2px solid #b7e4c7;">{fmt(tot_month_gwp)}</td>
            <td style="padding:12px 10px;text-align:right;color:#7ec89b;font-family:monospace;font-size:11.5px;border-top:2px solid #b7e4c7;">{fmt(tot_month_budg)}</td>
            <td style="padding:12px 10px;text-align:right;border-top:2px solid #b7e4c7;">{ach_badge(apr_ach)}</td>
            <td style="padding:12px 10px;text-align:right;color:#e2f5ea;font-family:monospace;font-size:11.5px;font-weight:600;border-top:2px solid #b7e4c7;">{fmt(tot_ytd_gwp)}</td>
            <td style="padding:12px 10px;text-align:right;color:#7ec89b;font-family:monospace;font-size:11.5px;border-top:2px solid #b7e4c7;">{fmt(tot_ytd_budg)}</td>
            <td style="padding:12px 14px 12px 10px;text-align:right;border-top:2px solid #b7e4c7;">{ach_badge(ytd_ach)}</td>
          </tr>
        </tfoot>
      </table>

    </td></tr>
  </table>

  <!-- FOOTER -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="margin-top:20px;background:#ffffff;border-radius:10px;border-collapse:collapse;">
    <tr><td style="padding:20px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>
        <td valign="middle">
          <div style="font-size:13px;font-weight:600;color:#1e293b;">{SIGNOFF_NAME}</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px;">{SIGNOFF_ROLE} &mdash; {COMPANY_NAME}</div>
          <div style="font-size:11px;color:#94a3b8;margin-top:2px;">
            H. Palmayrah 20069, Sosun Magu | Male', Maldives &nbsp;|&nbsp;
            T: +960 331 5262 &nbsp;|&nbsp; M: +960 7876575 &nbsp;|&nbsp;
            <a href="http://www.takaful.mv" style="color:#2e9954;text-decoration:none;">www.takaful.mv</a>
          </div>
        </td>
        <td valign="middle" align="right">
          <div style="font-size:10px;color:#cbd5e1;font-family:monospace;">Auto-generated by BI System</div>
          <div style="font-size:10px;color:#2e9954;font-family:monospace;font-weight:600;">{datetime.now().strftime("%d %b %Y %H:%M")}</div>
        </td>
      </tr></table>
    </td></tr>
  </table>

</div>
</body>
</html>"""
    return html


# -- STEP 5: SEND EMAIL --------------------------------------------------------
def send_me_email(me_name, me_email, html_body, subject):
    if TEST_MODE:
        to_addr    = CC_EMAIL
        recipients = [CC_EMAIL]
        test_tag   = f"[TEST - {me_name}] "
    else:
        to_addr    = me_email
        recipients = [me_email, CC_EMAIL]
        test_tag   = ""

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = test_tag + subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_addr
    if not TEST_MODE:
        msg["Cc"]  = CC_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        if TEST_MODE:
            print(f"[Email TEST] Sent {me_name} report to {CC_EMAIL}")
        else:
            print(f"[Email] Sent to {me_name} <{me_email}>")
    except Exception as e:
        print(f"[Email] ERROR for {me_name}: {e}")


# -- MAIN ----------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"[Start] ME Daily Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if SINGLE_ME_CODE:
        print(f"[Mode]  Single ME: {SINGLE_ME_CODE}")
    if TEST_MODE:
        print(f"[Mode]  TEST MODE - emails go to {CC_EMAIL}")
    print(f"{'='*60}\n")

    rpt_month, rpt_year, month_name, report_period, as_of_str = get_report_period()
    print(f"[Config] Period: {report_period} | As of: {as_of_str}\n")

    run_sync_scripts()

    me_list = fetch_me_list(rpt_month, rpt_year)
    if not me_list:
        print("[WARN] No MEs found. Exiting.")
        sys.exit(0)

    subject = f"Your GWP Performance - {report_period} (As of {as_of_str})"

    for me in me_list:
        me_code  = me["me_code"]
        me_name  = me["me_name"]
        me_email = me["email"]

        print(f"\n[ME] {me_name} ({me_code}) -> {me_email}")

        data = fetch_me_data(me_code, rpt_month, rpt_year)

        all_rows = data["health"] + data["life"] + data["general"]
        if not all_rows:
            print(f"[ME] No data found for {me_name} - skipping.")
            continue

        html = build_me_html(
            me_name, data, report_period,
            as_of_str, month_name, rpt_year
        )
        send_me_email(me_name, me_email, html, subject)

    print(f"\n[Done] {datetime.now().strftime('%Y-%m-%d %H:%M')}")