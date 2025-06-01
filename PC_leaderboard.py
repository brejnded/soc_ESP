import serial
import serial.tools.list_ports
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import os
import urllib.parse
import socket
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

# Configuration
SERIAL_PORT = None
BAUD_RATE = 115200
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = 8080
ADMIN_PASSWORD = "SPSIT" # CHANGE THIS
leaderboard_file = "leaderboard.json"
correct_answers_file = "correct_answers.json"

# Category Configuration
CATEGORY1_UID_STR = "0xF30xC70x1A0x130x3D"
CATEGORY2_UID_STR = "0x8A0x8D0x570x540x04"
CATEGORY3_UID_STR = "0x120x9C0x190xFA0x6D"
CATEGORY_UIDS = {
    CATEGORY1_UID_STR: "Category1",
    CATEGORY2_UID_STR: "Category2",
    CATEGORY3_UID_STR: "Category3",
}
CATEGORY_NAMES_CONFIG_KEYS = ["Category1", "Category2", "Category3"]

# --- Global Variables ---
leaderboard_data = []
correct_answers_config = {}

GENERAL_MAX_QUESTIONS = 15
NUM_QUESTIONS_PER_CATEGORY = {key: 15 for key in CATEGORY_NAMES_CONFIG_KEYS}
PENALTY_PER_INCORRECT = 60
CATEGORY_DISPLAY_NAMES = {key: f"Kategória {i+1}" for i, key in enumerate(CATEGORY_NAMES_CONFIG_KEYS)}
CATEGORY_DISPLAY_NAMES["All Categories"] = "Všetky kategórie"
CATEGORY_SECTIONS = {key: [] for key in CATEGORY_NAMES_CONFIG_KEYS}

# --- GUI and Serial Port Selection ---
def find_serial_port(root_window):
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        messagebox.showerror("Error", "No serial ports found. ESP32 connected?", parent=root_window)
        root_window.destroy(); return None
    if len(ports) == 1:
        print(f"Auto-selecting: {ports[0].device}")
        root_window.destroy(); return ports[0].device

    port_var = tk.StringVar(value=ports[0].device)
    selected_port_result = None
    def select_port_action():
        nonlocal selected_port_result
        selected_port_result = port_var.get()
        root_window.destroy()

    ttk.Label(root_window, text="Please select the ESP32 serial port:").pack(pady=(10,5))
    for port_info in ports:
        ttk.Radiobutton(root_window, text=f"{port_info.device} ({port_info.description})", variable=port_var, value=port_info.device).pack(anchor=tk.W, padx=20)
    ttk.Button(root_window, text="Select", command=select_port_action).pack(pady=10)
    root_window.protocol("WM_DELETE_WINDOW", root_window.destroy) # Allow closing
    root_window.mainloop() # This blocks until window is closed
    return selected_port_result

# --- Leaderboard Persistence & Management ---
def load_leaderboard():
    global leaderboard_data
    try:
        if os.path.exists(leaderboard_file):
            with open(leaderboard_file, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    leaderboard_data = loaded_data
                    for entry in leaderboard_data:
                        entry.setdefault("disqualified", False)
                        entry.setdefault("original_time", entry.get("time", 0) - entry.get("penalty", 0))
                    print("Leaderboard loaded from file.")
                else: leaderboard_data = [] # File exists but not a list
        else: leaderboard_data = [] # File doesn't exist
    except Exception as e:
        print(f"Error loading leaderboard: {e}. Starting fresh."); leaderboard_data = []

def save_leaderboard(data_to_save):
    global leaderboard_data
    try:
        if not isinstance(data_to_save, list): return # Safety
        with open(leaderboard_file, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        leaderboard_data = data_to_save # Update global after successful save
        print("Leaderboard saved to file.")
    except Exception as e: print(f"Error saving leaderboard: {e}")

def clear_leaderboard():
    global leaderboard_data
    leaderboard_data = []; save_leaderboard(leaderboard_data)
    print("Leaderboard cleared.")

def add_to_leaderboard(name, time_taken, answers, category_key):
    global leaderboard_data, correct_answers_config, PENALTY_PER_INCORRECT, NUM_QUESTIONS_PER_CATEGORY, CATEGORY_DISPLAY_NAMES

    category_correct_answers = get_correct_answers_for_category(correct_answers_config, category_key)
    penalty_seconds = 0
    disqualified = False
    expected_num_questions = NUM_QUESTIONS_PER_CATEGORY.get(category_key, GENERAL_MAX_QUESTIONS)
    if expected_num_questions <= 0: expected_num_questions = 1 # Safety net

    if len(answers) < expected_num_questions:
        disqualified = True
        for q_num in range(1, expected_num_questions + 1):
            if str(q_num) not in answers: penalty_seconds += PENALTY_PER_INCORRECT
    else:
        for q_num in range(1, expected_num_questions + 1):
            q_str = str(q_num)
            submitted_ans = answers.get(q_str)
            correct_ans = category_correct_answers.get(q_str)
            if submitted_ans is None or (correct_ans is not None and submitted_ans != correct_ans):
                penalty_seconds += PENALTY_PER_INCORRECT

    penalized_time = time_taken + penalty_seconds
    new_entry = {
        "name": name.strip(), "time": penalized_time, "original_time": time_taken,
        "penalty": penalty_seconds, "category": category_key, "disqualified": disqualified
    }

    current_lb_copy = list(leaderboard_data)
    existing_idx = -1
    for i, entry in enumerate(current_lb_copy):
        if entry["name"].strip() == new_entry["name"] and entry.get("category") == new_entry["category"]:
            existing_idx = i; break
    
    if existing_idx != -1:
        if (new_entry["disqualified"], new_entry["time"], new_entry["penalty"]) < \
           (current_lb_copy[existing_idx]["disqualified"], current_lb_copy[existing_idx]["time"], current_lb_copy[existing_idx]["penalty"]):
            current_lb_copy[existing_idx] = new_entry
        else: return # Not a better score
    else:
        current_lb_copy.append(new_entry)

    current_lb_copy.sort(key=lambda x: (x["disqualified"], x["time"], x["penalty"]))
    save_leaderboard(current_lb_copy)
    cat_display = CATEGORY_DISPLAY_NAMES.get(category_key, category_key)
    print(f"Leaderboard updated: {new_entry['name']} in {cat_display}, Time: {format_time(penalized_time, disqualified)}")

# --- Formatting and HTML/CSV Generation ---
def format_time(seconds, disqualified=False):
    if not isinstance(seconds, (int, float)) or seconds < 0: seconds = 0
    h = int(seconds // 3600); m = int((seconds % 3600) // 60); s = int(seconds % 60)
    time_str = f"{h:02d}:{m:02d}:{s:02d}"
    return f"D: {time_str}" if disqualified else time_str

def generate_leaderboard_csv(data_to_export):
    global CATEGORY_DISPLAY_NAMES
    csv_output = "Rank;Name;Category;Original Time;Penalty;Final Time;Status\n"
    for i, entry in enumerate(data_to_export):
        cat_key = entry.get("category", "N/A")
        cat_display = CATEGORY_DISPLAY_NAMES.get(cat_key, cat_key)
        status = "Disqualified" if entry.get("disqualified", False) else "Qualified"
        csv_output += (
            f"{i+1};{entry.get('name','N/A').replace(';',',')};{cat_display};"
            f"{format_time(entry.get('original_time',0))};{format_time(entry.get('penalty',0))};"
            f"{format_time(entry.get('time',0), entry.get('disqualified',False))};{status}\n"
        )
    return csv_output

def generate_leaderboard_html(leaderboard, selected_category="All Categories"):
    global CATEGORY_DISPLAY_NAMES
    cat_buttons_html = '<div style="text-align:center;margin-bottom:20px;">'
    for cat_key, cat_disp_name in CATEGORY_DISPLAY_NAMES.items():
        active_class = 'active' if cat_key == selected_category else ''
        cat_buttons_html += f'<form action="/" method="GET" style="display:inline;"><input type="hidden" name="category" value="{cat_key}"><button type="submit" class="button-link category-button {active_class}">{cat_disp_name}</button></form>'
    cat_buttons_html += "</div>"

    style = """<style>body{font-family:'Segoe UI',Verdana,sans-serif;background-color:#f8f9fa;color:#343a40;margin:0;padding:20px}.container{width:90%;max-width:950px;margin:20px auto;background-color:#fff;padding:30px;border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,.1)}h1{text-align:center;color:#0056b3}h1,table{margin-bottom:30px}th,td{border:1px solid #dee2e6;padding:10px 12px;text-align:left}th{background-color:#e9ecef}.header-controls{position:fixed;top:10px;right:20px}.button-link{display:inline-block;padding:10px 20px;margin:5px;color:#fff;text-decoration:none;border-radius:5px;border:none;cursor:pointer;background-color:#007bff}.button-link.admin{background-color:#28a745}.category-button{background-color:#6c757d}.category-button.active{background-color:#007bff;font-weight:700}table{border-collapse:collapse;width:100%;font-size:.95em}tr:nth-child(even){background-color:#f8f9fa}.disqualified td{color:#dc3545;font-style:italic}</style>"""
    script = """<script>function refreshLeaderboard(){var x=new XMLHttpRequest;x.onreadystatechange=function(){if(this.readyState==4&&this.status==200){var e=document.getElementById("leaderboard");e&&(e.innerHTML=this.responseText)}else this.readyState==4&&console.error("Refresh fail:"+this.status)};const e=(new URLSearchParams(window.location.search)).get("category")||"All Categories";x.open("GET","/leaderboard_table?category="+encodeURIComponent(e),!0);x.setRequestHeader("Cache-Control","no-cache");x.send()}document.addEventListener("DOMContentLoaded",function(){refreshLeaderboard();setInterval(refreshLeaderboard,10000)});</script>"""
    initial_table = generate_leaderboard_table_html(leaderboard)
    selected_cat_display = CATEGORY_DISPLAY_NAMES.get(selected_category, selected_category)
    return f'<!DOCTYPE html><html lang="sk"><head><meta charset="UTF-8"><title>Tabuľka - {selected_cat_display}</title>{style}{script}</head><body><div class="header-controls"><a href="/admin" class="button-link admin">Admin</a></div><div class="container"><h1>Tabuľka Výsledkov</h1>{cat_buttons_html}<div id="leaderboard">{initial_table}</div></div></body></html>'

def generate_leaderboard_table_html(leaderboard_to_display):
    global CATEGORY_DISPLAY_NAMES
    table_content = "<table><thead><tr><th>Poradie</th><th>Meno</th><th>Kategória</th><th>Pôvodný Čas</th><th>Penalizácia</th><th>Výsledný čas</th><th>Status</th></tr></thead><tbody>"
    if not leaderboard_to_display:
        table_content += '<tr><td colspan="7" style="text-align:center;padding:20px;">Žiadne výsledky v tejto kategórii.</td></tr>'
    else:
        for i, entry in enumerate(leaderboard_to_display):
            cat_key = entry.get("category", "N/A")
            cat_disp = CATEGORY_DISPLAY_NAMES.get(cat_key, cat_key)
            status = "Diskvalifikovaný" if entry.get("disqualified", False) else "Kvalifikovaný"
            row_cls = 'disqualified' if entry.get("disqualified", False) else ''
            table_content += (
                f'<tr class="{row_cls}"><td>{i+1}</td><td>{entry.get("name","N/A")}</td><td>{cat_disp}</td>'
                f'<td>{format_time(entry.get("original_time",0))}</td><td>{format_time(entry.get("penalty",0))}</td>'
                f'<td>{format_time(entry.get("time",0), entry.get("disqualified",False))}</td><td>{status}</td></tr>'
            )
    table_content += "</tbody></table>"
    return table_content

# --- Admin Page HTML Generation (MODIFIED for single form) ---
def generate_admin_html(config):
    global GENERAL_MAX_QUESTIONS, PENALTY_PER_INCORRECT, CATEGORY_DISPLAY_NAMES, NUM_QUESTIONS_PER_CATEGORY, CATEGORY_SECTIONS, ADMIN_PASSWORD

    penalty_val = PENALTY_PER_INCORRECT
    current_gen_max_q = GENERAL_MAX_QUESTIONS
    current_disp_names = CATEGORY_DISPLAY_NAMES
    current_num_q_cat = NUM_QUESTIONS_PER_CATEGORY
    current_cat_sections = CATEGORY_SECTIONS
    cat_conf_keys = CATEGORY_NAMES_CONFIG_KEYS

    admin_style = """<style>body{font-family:'Segoe UI',Verdana,sans-serif;background-color:#f8f9fa;color:#343a40;margin:0;padding:20px}.container{width:90%;max-width:1200px;margin:20px auto;background-color:#fff;padding:30px;border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,.1)}h1,h2,h3,h4{text-align:center;color:#0056b3;margin-bottom:15px;font-weight:600}h2{margin-top:30px;border-bottom:1px solid #dee2e6;padding-bottom:8px}h3{color:#17a2b8;margin-top:25px}h4{color:#28a745;font-size:1.1em;margin-top:15px;text-align:left;padding-left:5px}label{display:block;margin-top:10px;font-weight:600;margin-bottom:3px}input[type=text],input[type=number],select,input[type=password]{width:100%;padding:8px;margin-top:3px;margin-bottom:10px;border:1px solid #ced4da;border-radius:4px;box-sizing:border-box;font-size:.95em}.button-base{display:inline-block;padding:10px 20px;margin:8px 4px;color:#fff;text-decoration:none;border-radius:5px;border:none;cursor:pointer;font-size:.95em}.button-save{background-color:#28a745}.button-back{background-color:#6c757d}.button-export{background-color:#ffc107;color:#343a40}.button-reset{background-color:#dc3545}.button-add-section,.button-remove-section{background-color:#007bff;font-size:.85em;padding:5px 10px;margin-left:10px}.button-remove-section{background-color:#dc3545}.button-container{text-align:center;margin-top:25px;padding-top:15px;border-top:1px solid #eee}.config-section,.display-names-section,.per-category-q-count-section,.category-sections-definition-area{display:flex;flex-wrap:wrap;justify-content:space-around;gap:15px;margin-bottom:20px;padding:15px;border-radius:8px}.config-section{background-color:#f0f8ff;border:1px solid #b0e0e6}.display-names-section{background-color:#e6f7ff;border:1px solid #91d5ff}.per-category-q-count-section{background-color:#fffbe6;border:1px solid #ffe58f}.category-sections-definition-area{background-color:#f0fff0;border:1px solid #a2d2a2;margin-top:10px;flex-direction:column}.config-item,.form-group{flex:1;min-width:200px}.section-entry{display:flex;gap:10px;align-items:center;margin-bottom:8px;padding:8px;border:1px dashed #ccc;border-radius:4px;background-color:#fafafa}.section-entry label{margin-top:0;white-space:nowrap}.section-entry input[type=text]{flex-grow:1}.section-entry input[type=number]{width:80px;flex-shrink:0}.category-container{display:flex;justify-content:space-around;flex-wrap:wrap;gap:20px;margin-top:15px}.category-section{flex:1;min-width:300px;max-width:32%;border:1px solid #dee2e6;padding:15px;border-radius:8px;background-color:#f8f9fa}.category-answers-box{margin-top:8px}.answer-group{margin-bottom:5px;padding-left:15px}.validation-error{color:red;font-size:.9em;text-align:center;margin:5px 0 10px;min-height:1em}.section-sum-info{font-size:.9em;color:#007bff;margin-top:5px;text-align:right;padding-right:10px;min-height:1em}.category-config-item{border:1px solid #ddd;padding:15px;margin-bottom:20px;border-radius:5px}.reset-section{margin-top:30px;padding-top:20px;border-top:1px solid #eee}</style>"""

    # The JavaScript for sections is now part of SimpleRequestHandler.get_admin_sections_script()
    # It will be injected into the <head> by the calling do_GET method.

    page_html = f"""<!DOCTYPE html><html lang="sk"><head><meta charset="UTF-8"><title>Admin Nastavenia</title>{admin_style}
    {SimpleRequestHandler.get_admin_sections_script(None)}
    </head><body><div class="container"><h1>Admin - Nastavenia Súťaže</h1>
    
    <form action="/save_answers" method="post"> 
        <h2>Všeobecné Nastavenia</h2>
        <div class="config-section">
            <div class="config-item form-group">
                <label for="general_max_questions">Maximálny počet otázok celkovo (pre UI limity):</label>
                <input type="number" id="general_max_questions" name="general_max_questions" value="{current_gen_max_q}" min="1" required>
            </div>
            <div class="config-item form-group">
                <label for="penalty">Penalizácia za nesprávnu/nevyplnenú odpoveď (s):</label>
                <input type="number" id="penalty" name="penalty" value="{penalty_val}" min="0" required>
            </div>
        </div>

        <h2>Názvy Kategórií</h2>
        <div class="display-names-section">"""
    for key in cat_conf_keys:
        page_html += f'<div class="form-group"><label for="display_name_{key}">{key} (interný):</label><input type="text" id="display_name_{key}" name="display_name_{key}" value="{current_disp_names.get(key, key)}" required></div>'
    page_html += "</div>"

    page_html += "<h2>Konfigurácia Kategórií (Počty Otázok a Sekcie)</h2>"
    for cat_key_loop in cat_conf_keys:
        cat_disp_name_loop = current_disp_names.get(cat_key_loop, cat_key_loop)
        total_q_for_cat_loop = current_num_q_cat.get(cat_key_loop, current_gen_max_q)
        sections_for_cat_loop = current_cat_sections.get(cat_key_loop, [])
        page_html += f"""
        <div class="category-config-item">
            <h3>{cat_disp_name_loop}</h3>
            <div class="per-category-q-count-section">
                <div class="form-group">
                    <label for="num_questions_{cat_key_loop}">Celkový počet otázok pre '{cat_disp_name_loop}':</label>
                    <input type="number" id="num_questions_{cat_key_loop}" name="num_questions_{cat_key_loop}" value="{total_q_for_cat_loop}" min="1" max="{current_gen_max_q}" required oninput="updateCategorySectionSum('{cat_key_loop}')">
                </div>
            </div>
            <h4>Sekcie pre '{cat_disp_name_loop}' <button type="button" class="button-base button-add-section" onclick="addSectionEntry('{cat_key_loop}', document.getElementById('num_questions_{cat_key_loop}').value)">Pridať Sekciu</button></h4>
            <div id="sections_container_{cat_key_loop}" class="category-sections-definition-area">"""
        for i, sec in enumerate(sections_for_cat_loop):
            sec_name, sec_q = sec.get('name',''), sec.get('num_questions',1)
            page_html += f"""<div class="section-entry" id="section_entry_{cat_key_loop}_{i}">
                <label for="section_name_{cat_key_loop}_{i}">Názov:</label><input type="text" name="section_name_{cat_key_loop}[]" id="section_name_{cat_key_loop}_{i}" value="{sec_name}" placeholder="Názov sekcie" required>
                <label for="section_q_count_{cat_key_loop}_{i}">Otázok:</label><input type="number" name="section_q_count_{cat_key_loop}[]" id="section_q_count_{cat_key_loop}_{i}" value="{sec_q}" min="1" max="{total_q_for_cat_loop}" required oninput="updateCategorySectionSum('{cat_key_loop}')">
                <button type="button" class="button-base button-remove-section" onclick="removeSectionEntry('section_entry_{cat_key_loop}_{i}', '{cat_key_loop}')">Odstrániť</button>
            </div>"""
        page_html += f"""</div>
            <div style="text-align:right;margin-top:5px;"><div id="section_sum_info_{cat_key_loop}" class="section-sum-info"></div></div>
            <div id="sections_validation_error_{cat_key_loop}" class="validation-error"></div>
        </div>"""

    page_html += """
        <h2>Správne odpovede podľa kategórií a sekcií</h2>
        <p style="text-align:center;font-size:0.9em;color:#6c757d;">Nastavte správne odpovede. Polia sa prispôsobia definovaným sekciám a počtu otázok.</p>
        <div class="category-container">"""
    for cat_key_ans in cat_conf_keys:
        cat_hdr_name = current_disp_names.get(cat_key_ans, cat_key_ans)
        cat_ans_config = config.get("categories", {}).get(cat_key_ans, {})
        cat_sections_ans = current_cat_sections.get(cat_key_ans, [])
        num_total_q_cat_ans = current_num_q_cat.get(cat_key_ans, 0)
        page_html += f'<div class="category-section"><h3>{cat_hdr_name}</h3><div class="category-answers-box">'
        overall_q_count_cat = 0
        if not cat_sections_ans and num_total_q_cat_ans > 0: # Fallback if no sections
            page_html += f'<h4>Všeobecné otázky ({num_total_q_cat_ans} otázok)</h4>'
            for q_idx in range(1, num_total_q_cat_ans + 1):
                overall_q_count_cat += 1
                ans_key = f"answer_{cat_key_ans}_{overall_q_count_cat}"
                curr_ans = cat_ans_config.get(str(overall_q_count_cat), "")
                page_html += f'<div class="answer-group"><label for="{ans_key}">Otázka {q_idx} (celk. {overall_q_count_cat}):</label><select id="{ans_key}" name="{ans_key}"><option value="" {"s" if curr_ans=="" else ""}>--</option><option value="A" {"s" if curr_ans=="A" else ""}>A</option><option value="B" {"s" if curr_ans=="B" else ""}>B</option><option value="C" {"s" if curr_ans=="C" else ""}>C</option><option value="D" {"s" if curr_ans=="D" else ""}>D</option></select></div>'.replace('"s"','"selected"')
        else: # Sections are defined
            for sec_ans in cat_sections_ans:
                sec_name_ans, num_q_sec_ans = sec_ans.get("name","Bez názvu"), sec_ans.get("num_questions",0)
                page_html += f'<h4>Sekcia: {sec_name_ans} ({num_q_sec_ans} otázok)</h4>'
                for q_idx_sec in range(1, num_q_sec_ans + 1):
                    overall_q_count_cat += 1
                    ans_key = f"answer_{cat_key_ans}_{overall_q_count_cat}"
                    curr_ans = cat_ans_config.get(str(overall_q_count_cat), "")
                    page_html += f'<div class="answer-group"><label for="{ans_key}">Otázka {q_idx_sec} (celk. {overall_q_count_cat}):</label><select id="{ans_key}" name="{ans_key}"><option value="" {"s" if curr_ans=="" else ""}>--</option><option value="A" {"s" if curr_ans=="A" else ""}>A</option><option value="B" {"s" if curr_ans=="B" else ""}>B</option><option value="C" {"s" if curr_ans=="C" else ""}>C</option><option value="D" {"s" if curr_ans=="D" else ""}>D</option></select></div>'.replace('"s"','"selected"')
        page_html += "</div></div>"
    page_html += """</div>
        <div class="button-container">
            <button type="submit" class="button-base button-save">Uložiť Všetky Nastavenia a Odpovede</button>
        </div>
    </form> {/* SINGLE FORM END */}

    <div class="reset-section"><h2>Export výsledkov (CSV)</h2>""" # Export buttons
    page_html += f'<a href="/leaderboard_excel" class="button-base button-export" download="leaderboard_all.csv">Všetky Kategórie</a>'
    for key_exp in cat_conf_keys:
        page_html += f'<a href="/leaderboard_excel_category?category={key_exp}" class="button-base button-export" download="leaderboard_{current_disp_names.get(key_exp,key_exp).replace(" ","_")}.csv">Export {current_disp_names.get(key_exp,key_exp)}</a>'
    page_html += "</div>"
    
    page_html += f"""
    <div class="reset-section"><h2>Reset tabuľky</h2><p>Vymaže VŠETKY výsledky!</p>
        <div class="form-group" style="max-width:300px;margin:auto;">
            <label for="resetPassword">Admin Heslo pre Reset:</label><input type="password" id="resetPassword" name="resetPassword" required>
        </div>
        <div class="button-container" style="border:none;padding-top:0;">
            <button type="button" onclick="checkPasswordAndReset()" class="button-base button-reset">Resetovať Tabuľku</button>
        </div>
    </div>
    <script>function checkPasswordAndReset(){{var p=document.getElementById('resetPassword').value;if(!p){{alert('Zadajte heslo.');return}}if(p==='{ADMIN_PASSWORD}'){{if(confirm('Naozaj VYMAZAŤ VŠETKY VÝSLEDKY?')){{if(confirm('Posledné varovanie! Naozaj?')){{var x=new XMLHttpRequest;x.open('POST','/admin_reset',!0);x.setRequestHeader('Content-type','application/x-www-form-urlencoded');x.onload=function(){{200<=this.status&&300>this.status?(alert('Tabuľka resetovaná!'),window.location.reload()):alert('Chyba resetu: '+this.status)}};x.send('password='+encodeURIComponent(p))}}}}}}else alert('Nesprávne heslo.')}}</script>"""

    page_html += f"""
    <div class="reset-section"><h2>Manuálne Pridanie Záznamu</h2>
        <form action="/admin_manual_add" method="post" class="manual-entry-section" style="border-top:none;padding-top:0;">
            <div class="manual-entry-grid">
                <div class="form-group"><label for="manual_name">Meno:</label><input type="text" id="manual_name" name="manual_name" required></div>
                <div class="form-group"><label for="manual_time">Pôvodný Čas (s):</label><input type="number" id="manual_time" name="manual_time" min="0" required></div>
                <div class="form-group"><label for="manual_category">Kategória:</label><select id="manual_category" name="manual_category" required><option value="" disabled selected>-- Vyberte --</option>"""
    for key_man in cat_conf_keys: page_html += f'<option value="{key_man}">{current_disp_names.get(key_man, key_man)}</option>'
    page_html += """</select></div></div><div class="manual-entry-answers"><h4>Odpovede Účastníka (max """ + str(current_gen_max_q) + """):</h4><div class="manual-entry-answers-grid">"""
    for q_man in range(1, current_gen_max_q + 1): page_html += f'<div class="form-group"><label for="manual_answer_{q_man}">Ot.{q_man}:</label><select id="manual_answer_{q_man}" name="manual_answer_{q_man}"><option value="">--</option><option value="A">A</option><option value="B">B</option><option value="C">C</option><option value="D">D</option></select></div>'
    page_html += """</div></div><div class="form-group" style="max-width:300px;margin:20px auto 0;"><label for="manual_password">Admin Heslo:</label><input type="password" id="manual_password" name="manual_password" required></div>
            <div class="button-container" style="border:none;padding-top:10px;"><button type="submit" class="button-base button-save">Pridať Záznam</button></div>
        </form>
    </div>
    <div class="button-container"><a href="/" class="button-base button-back">Späť na Hlavnú Tabuľku</a></div>
    </div></body></html>"""
    return page_html

# --- Helper and Config Functions (MODIFIED) ---
def get_category_name_from_uid_str(uid_str):
    return CATEGORY_UIDS.get(uid_str, None)

def load_correct_answers_config():
    global correct_answers_config, PENALTY_PER_INCORRECT, GENERAL_MAX_QUESTIONS, \
           CATEGORY_DISPLAY_NAMES, NUM_QUESTIONS_PER_CATEGORY, CATEGORY_SECTIONS

    def_penalty = 60; def_gen_max_q = 15
    def_num_q_cat = {k: def_gen_max_q for k in CATEGORY_NAMES_CONFIG_KEYS}
    def_disp_names = {k: f"Kategória {i+1}" for i, k in enumerate(CATEGORY_NAMES_CONFIG_KEYS)}
    def_disp_names["All Categories"] = "Všetky kategórie"
    def_cat_sections = {k: [] for k in CATEGORY_NAMES_CONFIG_KEYS}

    default_struct = {
        "penalty": def_penalty, "general_max_questions": def_gen_max_q,
        "num_questions_per_category": def_num_q_cat.copy(),
        "category_display_names": def_disp_names.copy(),
        "categories": {k: {} for k in CATEGORY_NAMES_CONFIG_KEYS},
        "category_sections": def_cat_sections.copy()
    }
    if not os.path.exists(correct_answers_file):
        print(f"{correct_answers_file} not found. Creating with defaults.")
        correct_answers_config = default_struct.copy()
        save_correct_answers_config(correct_answers_config) # This will also set globals

    try:
        with open(correct_answers_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict) or not all(k in config for k in default_struct.keys()):
            raise ValueError("Invalid config structure, reverting to defaults.")
        
        correct_answers_config = config # Store loaded config
        PENALTY_PER_INCORRECT = max(0, int(config.get("penalty", def_penalty)))
        GENERAL_MAX_QUESTIONS = max(1, int(config.get("general_max_questions", def_gen_max_q)))
        
        loaded_num_q_cat = config.get("num_questions_per_category", def_num_q_cat)
        NUM_QUESTIONS_PER_CATEGORY = {k: max(1, min(int(loaded_num_q_cat.get(k, def_gen_max_q)), GENERAL_MAX_QUESTIONS)) for k in CATEGORY_NAMES_CONFIG_KEYS}

        loaded_disp_names = config.get("category_display_names", def_disp_names)
        CATEGORY_DISPLAY_NAMES = def_disp_names.copy(); CATEGORY_DISPLAY_NAMES.update(loaded_disp_names)
        
        loaded_cat_sections = config.get("category_sections", def_cat_sections)
        CATEGORY_SECTIONS = {k: [] for k in CATEGORY_NAMES_CONFIG_KEYS} # Ensure all keys exist
        for cat_k, sections_list in loaded_cat_sections.items():
            if cat_k in CATEGORY_SECTIONS and isinstance(sections_list, list):
                valid_sections = []
                current_sum_q = 0
                total_q_for_cat_val = NUM_QUESTIONS_PER_CATEGORY.get(cat_k, 0)
                for sec_item in sections_list:
                    if isinstance(sec_item, dict) and "name" in sec_item and "num_questions" in sec_item:
                        try:
                            q_count = int(sec_item["num_questions"])
                            if q_count > 0:
                                valid_sections.append({"name": str(sec_item["name"]), "num_questions": q_count})
                                current_sum_q += q_count
                        except ValueError: pass # Skip if num_questions not int
                # Basic validation on load - if sections exist, their sum should ideally match total_q
                # This is more for data integrity check; admin UI/save is stricter
                if valid_sections and current_sum_q != total_q_for_cat_val:
                    print(f"Warning on load: For '{cat_k}', section sum ({current_sum_q}) != total Q ({total_q_for_cat_val}). Using loaded sections but review needed.")
                CATEGORY_SECTIONS[cat_k] = valid_sections

        print("Config loaded from file.")

    except Exception as e:
        print(f"Error loading or validating config: {e}. Using/saving defaults.")
        correct_answers_config = default_struct.copy() # Use pristine defaults
        save_correct_answers_config(correct_answers_config) # This re-saves and sets globals from defaults


def save_correct_answers_config(config_to_save):
    global correct_answers_config, PENALTY_PER_INCORRECT, GENERAL_MAX_QUESTIONS, \
           CATEGORY_DISPLAY_NAMES, NUM_QUESTIONS_PER_CATEGORY, CATEGORY_SECTIONS
    try:
        # Ensure all top-level keys from default_struct are present
        for key, default_value in {
            "penalty": 60, "general_max_questions": 15,
            "num_questions_per_category": {k: 15 for k in CATEGORY_NAMES_CONFIG_KEYS},
            "category_display_names": {**{k: f"K{i+1}" for i,k in enumerate(CATEGORY_NAMES_CONFIG_KEYS)}, "All Categories":"Všetky"},
            "categories": {k: {} for k in CATEGORY_NAMES_CONFIG_KEYS},
            "category_sections": {k: [] for k in CATEGORY_NAMES_CONFIG_KEYS}
        }.items():
            if key not in config_to_save: # Add if missing
                 config_to_save[key] = default_value.copy() if isinstance(default_value, (dict, list)) else default_value


        # Validate general_max_questions
        try: config_to_save["general_max_questions"] = max(1, int(config_to_save["general_max_questions"]))
        except: config_to_save["general_max_questions"] = 15
        gen_max_q_val = config_to_save["general_max_questions"]

        # Validate num_questions_per_category and sections together
        for cat_key_s in CATEGORY_NAMES_CONFIG_KEYS:
            try: total_q_cat = max(1, min(int(config_to_save["num_questions_per_category"].get(cat_key_s, gen_max_q_val)), gen_max_q_val))
            except: total_q_cat = min(gen_max_q_val, 15)
            config_to_save["num_questions_per_category"][cat_key_s] = total_q_cat

            current_sections = config_to_save["category_sections"].get(cat_key_s, [])
            valid_sections_for_save = []
            current_section_q_sum_val = 0
            if isinstance(current_sections, list):
                for sec_data in current_sections:
                    if isinstance(sec_data, dict) and "name" in sec_data and "num_questions" in sec_data:
                        try:
                            q_c = int(sec_data["num_questions"])
                            if q_c > 0 and sec_data["name"].strip():
                                valid_sections_for_save.append({"name": sec_data["name"].strip(), "num_questions": q_c})
                                current_section_q_sum_val += q_c
                        except ValueError: pass # Invalid q_count
            
            if valid_sections_for_save and current_section_q_sum_val != total_q_cat:
                print(f"Correcting section sum for '{cat_key_s}': sum {current_section_q_sum_val} != total {total_q_cat}. Sections cleared for this category.")
                config_to_save["category_sections"][cat_key_s] = [] # Clear if sum mismatch and sections were defined
            elif not valid_sections_for_save and total_q_cat > 0 : # if no sections defined but total_q > 0
                 config_to_save["category_sections"][cat_key_s] = [] # ensure it's an empty list
            else:
                config_to_save["category_sections"][cat_key_s] = valid_sections_for_save


            # Clean answers for this category
            cat_answers_data = config_to_save["categories"].get(cat_key_s, {})
            if isinstance(cat_answers_data, dict):
                keys_to_delete = [k_str for k_str in cat_answers_data if not k_str.isdigit() or int(k_str) > total_q_cat]
                for k_del_ans in keys_to_delete: del cat_answers_data[k_del_ans]
            else: config_to_save["categories"][cat_key_s] = {}


        with open(correct_answers_file, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, ensure_ascii=False, indent=4)
        print("Config and answers saved successfully.")

        # Update globals from the successfully saved and validated config
        correct_answers_config = config_to_save.copy() # Use a copy
        PENALTY_PER_INCORRECT = correct_answers_config["penalty"]
        GENERAL_MAX_QUESTIONS = correct_answers_config["general_max_questions"]
        NUM_QUESTIONS_PER_CATEGORY = correct_answers_config["num_questions_per_category"].copy()
        CATEGORY_DISPLAY_NAMES = correct_answers_config["category_display_names"].copy()
        CATEGORY_SECTIONS = correct_answers_config["category_sections"].copy()

    except Exception as e:
        print(f"CRITICAL Error during save_correct_answers_config: {e}")
        import traceback; traceback.print_exc()


def get_correct_answers_for_category(glob_config, category_key_lookup):
    return glob_config.get("categories", {}).get(category_key_lookup, {})

def filter_leaderboard_by_category(lb_data, cat_key_filter):
    if cat_key_filter == "All Categories" or not cat_key_filter: return lb_data
    return [entry for entry in lb_data if entry.get("category") == cat_key_filter]

# --- Serial Listener Thread ---
def serial_listener():
    global leaderboard_data, correct_answers_config, SERIAL_PORT, BAUD_RATE
    if SERIAL_PORT is None: print("Serial port not set for listener."); return
    active_connection = None
    while True:
        try:
            print(f"Attempting serial connection to {SERIAL_PORT}...")
            active_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            print(f"Serial connected: {SERIAL_PORT}")
            data_buffer = ""
            while True: # Inner loop for reading data
                if active_connection.in_waiting > 0:
                    data_buffer += active_connection.read(active_connection.in_waiting).decode('utf-8', errors='ignore')
                    while '\n' in data_buffer:
                        json_line, data_buffer = data_buffer.split('\n', 1)
                        json_line = json_line.strip()
                        if not json_line: continue
                        try:
                            parsed_data = json.loads(json_line)
                            if isinstance(parsed_data,dict) and all(k in parsed_data for k in ["name","time","answers","category_uid"]):
                                cat_k = get_category_name_from_uid_str(parsed_data["category_uid"])
                                if cat_k:
                                    add_to_leaderboard(parsed_data["name"], float(parsed_data["time"]), parsed_data["answers"], cat_k)
                                else: print(f"Warning: Unrecognized category UID from serial: {parsed_data['category_uid']}")
                            else: print(f"Warning: Invalid JSON structure from serial: {json_line}")
                        except json.JSONDecodeError: print(f"Serial JSON decode error: '{json_line}'")
                        except Exception as proc_err: print(f"Error processing serial data ('{json_line}'): {proc_err}")
                time.sleep(0.05) # Polling interval
        except serial.SerialException as ser_err:
            print(f"Serial connection error ({SERIAL_PORT}): {ser_err}. Retrying in 5s...")
            if active_connection and active_connection.is_open: active_connection.close()
            active_connection = None; time.sleep(5)
        except KeyboardInterrupt: print("Serial listener stopping."); break
        except Exception as e_listen:
            print(f"Unexpected error in serial listener: {e_listen}. Retrying in 10s...")
            if active_connection and active_connection.is_open: active_connection.close()
            active_connection = None; time.sleep(10)
    if active_connection and active_connection.is_open: active_connection.close()
    print("Serial listener terminated.")


# --- HTTP Request Handler (MODIFIED) ---
class SimpleRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format_str, *args_list): return # Quieter logging

    @staticmethod # Make it static so it can be called without an instance if needed by generate_admin_html
    def get_admin_sections_script(dummy_self_param_to_match_method_signature=None):
        # JavaScript for dynamically adding/removing sections and validating sums
        return """<script>
        let sectionCounters = {};
        function initializeSectionCounters() { const cK = """ + json.dumps(CATEGORY_NAMES_CONFIG_KEYS) + """;cK.forEach(k=>{const co=document.getElementById('sections_container_'+k);sectionCounters[k]=co?co.getElementsByClassName('section-entry').length:0;});}
        function addSectionEntry(cK,maxQTotal){const co=document.getElementById('sections_container_'+cK);if(!co)return;const sIdx=sectionCounters[cK]++;const eD=document.createElement('div');eD.className='section-entry';eD.id=`section_entry_${cK}_${sIdx}`;eD.innerHTML=`<label for="section_name_${cK}_${sIdx}">Názov:</label><input type="text" name="section_name_${cK}[]" id="section_name_${cK}_${sIdx}" placeholder="Názov sekcie" required><label for="section_q_count_${cK}_${sIdx}">Otázok:</label><input type="number" name="section_q_count_${cK}[]" id="section_q_count_${cK}_${sIdx}" value="1" min="1" max="${maxQTotal}" required oninput="updateCategorySectionSum('${cK}')"><button type="button" class="button-base button-remove-section" onclick="removeSectionEntry('section_entry_${cK}_${sIdx}','${cK}')">Odstrániť</button>`;co.appendChild(eD);updateCategorySectionSum(cK);}
        function removeSectionEntry(eId,cK){const e=document.getElementById(eId);if(e)e.remove();updateCategorySectionSum(cK);}
        function updateCategorySectionSum(cK){const co=document.getElementById('sections_container_'+cK);const tQI=document.getElementById('num_questions_'+cK);const sID=document.getElementById('section_sum_info_'+cK);const eDv=document.getElementById('sections_validation_error_'+cK);if(!co||!tQI||!sID||!eDv)return;const tA=parseInt(tQI.value)||0;let cSS=0;const sQIs=co.querySelectorAll('input[name^="section_q_count_'+cK+'"]');sQIs.forEach(i=>{cSS+=parseInt(i.value)||0;});sID.textContent=`Súčet v sekciách: ${cSS} / ${tA}`;if(cSS!==tA&&sQIs.length>0){eDv.textContent='POZOR: Súčet v sekciách sa nerovná celkovému počtu otázok!';sID.style.color='red';tQI.style.borderColor='red';}else{eDv.textContent='';sID.style.color=cSS===tA&&sQIs.length>0?'green':'#007bff';tQI.style.borderColor='';}}
        document.addEventListener('DOMContentLoaded',()=>{initializeSectionCounters();const cK=""" + json.dumps(CATEGORY_NAMES_CONFIG_KEYS) + """;cK.forEach(k=>{updateCategorySectionSum(k);const tCI=document.getElementById('num_questions_'+k);if(tCI)tCI.addEventListener('input',()=>updateCategorySectionSum(k));});});
        </script>"""

    def do_GET(self):
        global leaderboard_data, correct_answers_config, CATEGORY_DISPLAY_NAMES, CATEGORY_NAMES_CONFIG_KEYS
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path
        query_data = urllib.parse.parse_qs(parsed_url.query)

        try:
            if req_path == "/":
                sel_cat_key = query_data.get("category", ["All Categories"])[0]
                if sel_cat_key not in CATEGORY_DISPLAY_NAMES: sel_cat_key = "All Categories"
                filtered_lb_data = filter_leaderboard_by_category(list(leaderboard_data), sel_cat_key)
                self.send_html_response(generate_leaderboard_html(filtered_lb_data, sel_cat_key))
            elif req_path == "/admin":
                self.send_html_response(generate_admin_html(correct_answers_config.copy())) # Pass a copy
            elif req_path == "/leaderboard_table":
                sel_cat_key_table = query_data.get("category", ["All Categories"])[0]
                if sel_cat_key_table not in CATEGORY_DISPLAY_NAMES: sel_cat_key_table = "All Categories"
                filtered_lb_table = filter_leaderboard_by_category(list(leaderboard_data), sel_cat_key_table)
                table_html_content = generate_leaderboard_table_html(filtered_lb_table)
                self.send_response(200); self.send_header("Content-type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-cache")
                self.end_headers(); self.wfile.write(table_html_content.encode("utf-8"))
            elif req_path == "/leaderboard_excel":
                self.send_csv_response(generate_leaderboard_csv(list(leaderboard_data)), "leaderboard_vsetky_kategorie.csv")
            elif req_path == "/leaderboard_excel_category":
                cat_key_csv = query_data.get("category", [""])[0]
                if cat_key_csv not in CATEGORY_NAMES_CONFIG_KEYS: # Ensure valid category for specific export
                    self.send_error(400, "Bad Request", "Invalid category for CSV export."); return
                filtered_lb_csv = filter_leaderboard_by_category(list(leaderboard_data), cat_key_csv)
                file_name_csv = f"leaderboard_{CATEGORY_DISPLAY_NAMES.get(cat_key_csv,cat_key_csv).replace(' ','_')}.csv"
                self.send_csv_response(generate_leaderboard_csv(filtered_lb_csv), file_name_csv)
            else: self.send_error(404, "Not Found", f"Resource '{req_path}' not found.")
        except Exception as e_get:
             print(f"Error handling GET {self.path}: {e_get}")
             if not getattr(self, 'headers_sent', False): self.send_error(500, "Internal Server Error")

    def do_POST(self):
        req_path_post = self.path
        try:
            if req_path_post == "/save_answers": self.handle_save_answers()
            elif req_path_post == "/admin_reset": self.handle_admin_reset()
            elif req_path_post == "/admin_manual_add": self.handle_manual_add()
            elif req_path_post == "/add": self.handle_add_via_post() # For testing/ESP32
            else: self.send_error(405, "Method Not Allowed", f"POST not supported for '{req_path_post}'.")
        except Exception as e_post:
             print(f"Error handling POST {self.path}: {e_post}")
             if not getattr(self, 'headers_sent', False): self.send_error(500, "Internal Server Error")

    def handle_save_answers(self):
        global GENERAL_MAX_QUESTIONS, PENALTY_PER_INCORRECT, CATEGORY_DISPLAY_NAMES, NUM_QUESTIONS_PER_CATEGORY, CATEGORY_SECTIONS, correct_answers_config
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            if content_len > 50 * 1024: self.send_error(413, "Payload Too Large"); return
            form_post_data = self.rfile.read(content_len).decode('utf-8')
            parsed_form = urllib.parse.parse_qs(form_post_data)

            # Start with a deep copy of current config to modify
            cfg_to_update = {
                "penalty": PENALTY_PER_INCORRECT,
                "general_max_questions": GENERAL_MAX_QUESTIONS,
                "num_questions_per_category": NUM_QUESTIONS_PER_CATEGORY.copy(),
                "category_display_names": CATEGORY_DISPLAY_NAMES.copy(),
                "categories": {k:v.copy() for k,v in correct_answers_config.get("categories", {}).items()}, # Correct answers
                "category_sections": {k: [s.copy() for s in v] for k,v in CATEGORY_SECTIONS.items()}
            }

            # 1. General Config
            cfg_to_update["penalty"] = max(0, int(parsed_form.get("penalty", [str(cfg_to_update['penalty'])])[0]))
            cfg_to_update["general_max_questions"] = max(1, int(parsed_form.get("general_max_questions", [str(cfg_to_update['general_max_questions'])])[0]))
            current_gen_max_q_val = cfg_to_update["general_max_questions"]

            # 2. Category Display Names & Total Questions per Category
            for key_cfg in CATEGORY_NAMES_CONFIG_KEYS:
                # Display Name
                disp_name = parsed_form.get(f"display_name_{key_cfg}", [cfg_to_update["category_display_names"].get(key_cfg,key_cfg)])[0].strip()
                cfg_to_update["category_display_names"][key_cfg] = disp_name if disp_name else f"Kategória {CATEGORY_NAMES_CONFIG_KEYS.index(key_cfg)+1}"
                
                # Total Questions for this category
                try:
                    num_q = int(parsed_form.get(f"num_questions_{key_cfg}", [str(cfg_to_update["num_questions_per_category"].get(key_cfg, current_gen_max_q_val))])[0])
                    cfg_to_update["num_questions_per_category"][key_cfg] = max(1, min(num_q, current_gen_max_q_val))
                except (ValueError, IndexError): # Keep old if invalid
                    cfg_to_update["num_questions_per_category"][key_cfg] = cfg_to_update["num_questions_per_category"].get(key_cfg, current_gen_max_q_val)
            
            # 3. Category Sections
            for cat_key_sec in CATEGORY_NAMES_CONFIG_KEYS:
                sec_names_list = parsed_form.get(f"section_name_{cat_key_sec}[]", [])
                sec_q_counts_str_list = parsed_form.get(f"section_q_count_{cat_key_sec}[]", [])
                
                parsed_cat_sections = []
                current_sec_q_sum_val = 0
                for i in range(len(sec_names_list)):
                    s_name = sec_names_list[i].strip()
                    try:
                        s_q_count = int(sec_q_counts_str_list[i])
                        if s_name and s_q_count > 0:
                            parsed_cat_sections.append({"name": s_name, "num_questions": s_q_count})
                            current_sec_q_sum_val += s_q_count
                    except (ValueError, IndexError): pass # Skip invalid section entry

                total_q_for_cat_val = cfg_to_update["num_questions_per_category"].get(cat_key_sec, 0)
                if parsed_cat_sections and current_sec_q_sum_val != total_q_for_cat_val:
                    print(f"Admin Save Warning: For '{cat_key_sec}', section sum ({current_sec_q_sum_val}) != total Q ({total_q_for_cat_val}). Sections for this category might be cleared by save_correct_answers_config if strict.")
                    # save_correct_answers_config will do final validation and decide to clear/keep
                cfg_to_update["category_sections"][cat_key_sec] = parsed_cat_sections
            
            # 4. Correct Answers (based on overall question number per category)
            new_correct_answers_all_cats = {k:{} for k in CATEGORY_NAMES_CONFIG_KEYS}
            for cat_key_ans_save in CATEGORY_NAMES_CONFIG_KEYS:
                total_q_in_cat_save = cfg_to_update["num_questions_per_category"].get(cat_key_ans_save, 0)
                for q_overall in range(1, total_q_in_cat_save + 1):
                    ans_form_key_name = f"answer_{cat_key_ans_save}_{q_overall}"
                    ans_val_list = parsed_form.get(ans_form_key_name, [""])
                    ans_value = urllib.parse.unquote_plus(ans_val_list[0]).strip() if ans_val_list else ""
                    if ans_value in ["A", "B", "C", "D"]:
                        new_correct_answers_all_cats[cat_key_ans_save][str(q_overall)] = ans_value
            cfg_to_update["categories"] = new_correct_answers_all_cats

            # 5. Save the complete validated configuration
            save_correct_answers_config(cfg_to_update) # This function also updates globals
            self.send_redirect_response("/admin")
        except Exception as e_save:
            print(f"CRITICAL Error in handle_save_answers: {e_save}")
            import traceback; traceback.print_exc()
            if not getattr(self, 'headers_sent', False): self.send_error(500, "Internal Server Error", "Failed to save configuration.")

    def handle_admin_reset(self):
        try:
            content_len_reset = int(self.headers.get('Content-Length',0)); post_data_reset = self.rfile.read(content_len_reset).decode('utf-8')
            form_data_reset = urllib.parse.parse_qs(post_data_reset)
            if form_data_reset.get("password",[""])[0] == ADMIN_PASSWORD:
                clear_leaderboard(); self.send_response(204); self.end_headers()
                print("Leaderboard reset successfully via admin.")
            else: 
                self.send_response(403); self.send_header("Content-type","text/html;charset=utf-8"); self.end_headers()
                self.wfile.write("<h1>403 Forbidden</h1><p>Incorrect admin password for reset.</p><p><a href='/admin'>Back</a></p>".encode('utf-8'))
        except Exception as e_reset: 
            print(f"Error during admin_reset: {e_reset}")
            if not getattr(self, 'headers_sent', False): self.send_error(500, "Reset failed.")

    def handle_manual_add(self):
        global GENERAL_MAX_QUESTIONS, CATEGORY_NAMES_CONFIG_KEYS, ADMIN_PASSWORD
        try:
            content_len_man = int(self.headers.get('Content-Length',0)); post_data_man = self.rfile.read(content_len_man).decode('utf-8')
            form_data_man = urllib.parse.parse_qs(post_data_man)

            if form_data_man.get("manual_password",[""])[0] != ADMIN_PASSWORD:
                self.send_response(403); self.send_header("Content-type","text/html;charset=utf-8"); self.end_headers()
                self.wfile.write("<h1>403 Forbidden</h1><p>Incorrect admin password for manual add.</p><p><a href='/admin'>Back</a></p>".encode('utf-8'))
                return

            man_name = form_data_man.get("manual_name",[""])[0].strip()
            man_time_str = form_data_man.get("manual_time",["0"])[0]
            man_cat_key = form_data_man.get("manual_category",[""])[0]

            if not man_name or not man_cat_key or man_cat_key not in CATEGORY_NAMES_CONFIG_KEYS:
                self.send_error(400, "Bad Request", "Missing name or invalid category for manual add."); return
            try: man_time_sec = int(man_time_str); assert man_time_sec >= 0
            except: self.send_error(400, "Bad Request", "Invalid time for manual add."); return
            
            man_answers_dict = {}
            # Manual entry form allows answers up to GENERAL_MAX_QUESTIONS
            # add_to_leaderboard will use NUM_QUESTIONS_PER_CATEGORY[man_cat_key] for scoring
            for q_idx_man in range(1, GENERAL_MAX_QUESTIONS + 1):
                ans_man = form_data_man.get(f"manual_answer_{q_idx_man}",[""])[0].strip()
                if ans_man in ["A","B","C","D"]: man_answers_dict[str(q_idx_man)] = ans_man
            
            add_to_leaderboard(man_name, float(man_time_sec), man_answers_dict, man_cat_key)
            self.send_redirect_response("/") # Redirect to main leaderboard
            print(f"Manual entry for '{man_name}' added.")
        except Exception as e_man_add:
            print(f"Error during manual_add: {e_man_add}")
            if not getattr(self, 'headers_sent', False): self.send_error(500, "Manual add failed.")

    def handle_add_via_post(self): # For ESP32 or testing
        try:
            content_len_add = int(self.headers.get('Content-Length',0)); post_data_add = self.rfile.read(content_len_add)
            json_payload = json.loads(post_data_add.decode('utf-8'))
            if isinstance(json_payload, dict) and all(k in json_payload for k in ["name","time","answers","category_uid"]):
                cat_key_add = get_category_name_from_uid_str(json_payload["category_uid"])
                if cat_key_add:
                    add_to_leaderboard(json_payload["name"], float(json_payload["time"]), json_payload["answers"], cat_key_add)
                    self.send_response(201); self.end_headers(); print(f"Entry added via POST for {json_payload['name']}")
                else: self.send_error(400, "Bad Request", f"Invalid category_uid in POST: {json_payload['category_uid']}")
            else: self.send_error(400, "Bad Request", "Invalid JSON structure for POST /add")
        except json.JSONDecodeError: self.send_error(400, "Bad Request", "Malformed JSON in POST /add")
        except Exception as e_add_post:
            print(f"Error during POST /add: {e_add_post}")
            if not getattr(self, 'headers_sent', False): self.send_error(500, "POST /add failed.")

    def send_html_response(self, html_str):
        try:
            encoded_content = html_str.encode("utf-8")
            self.send_response(200); self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded_content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache"); self.send_header("Expires", "0")
            self.end_headers(); self.wfile.write(encoded_content)
            setattr(self, 'headers_sent', True)
        except Exception as e_send_html:
             print(f"Error sending HTML response: {e_send_html}")
             if not getattr(self, 'headers_sent', False): # Try to send error if headers not already sent
                 try: self.send_error(500, "Internal Server Error", "Failed to generate HTML response")
                 except: pass # Ignore error during error sending

    def send_csv_response(self, csv_content_str, file_name_str):
        try:
            bom_plus_csv_bytes = b'\xef\xbb\xbf' + csv_content_str.encode("utf-8") # BOM for Excel
            self.send_response(200); self.send_header("Content-type", "text/csv; charset=utf-8")
            safe_file_name = urllib.parse.quote(file_name_str.replace('"', "'"))
            self.send_header("Content-Disposition", f'attachment; filename="{safe_file_name}"')
            self.send_header("Content-Length", str(len(bom_plus_csv_bytes)))
            self.end_headers(); self.wfile.write(bom_plus_csv_bytes)
            setattr(self, 'headers_sent', True)
        except Exception as e_send_csv:
             print(f"Error sending CSV response ({file_name_str}): {e_send_csv}")
             if not getattr(self, 'headers_sent', False):
                 try: self.send_error(500, "Internal Server Error", "Failed to generate CSV")
                 except: pass
    
    def send_redirect_response(self, target_location):
        try:
            self.send_response(303); self.send_header("Location", target_location); self.end_headers() # 303 See Other for POST redirect
            setattr(self, 'headers_sent', True)
        except Exception as e_redirect: print(f"Error sending redirect to {target_location}: {e_redirect}")


# --- Network and UI Helpers ---
def get_server_ip():
    s_ip = None
    try:
        s_ip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s_ip.settimeout(0.1)
        s_ip.connect(("8.8.8.8", 80)); local_ip_addr = s_ip.getsockname()[0]
        if not local_ip_addr.startswith("127."): return local_ip_addr
    except Exception: pass
    finally:
        if s_ip: s_ip.close()
    try: # Fallback
        host_name = socket.gethostname(); local_ip_addr_fb = socket.gethostbyname(host_name)
        if not local_ip_addr_fb.startswith("127."): return local_ip_addr_fb
    except Exception: pass
    return "localhost"

def show_ip_popup(ip_addr, port_num):
    popup_win = tk.Tk(); popup_win.title("Server beží"); popup_win.attributes('-topmost', True)
    popup_win.geometry("380x130"); popup_win.resizable(False, False)
    tk.Label(popup_win, text="Web server beží na adrese:", font=("Segoe UI", 10)).pack(pady=(10,2))
    server_url = f"http://{ip_addr}:{port_num}"; localhost_url = f"http://localhost:{port_num}"
    url_field = tk.Entry(popup_win, width=45, font=("Segoe UI", 10, "bold"), bd=0, relief=tk.FLAT, justify='center')
    url_field.insert(0, server_url); url_field.config(state='readonly', readonlybackground='white', fg='blue'); url_field.pack(pady=1)
    if ip_addr != "localhost":
        tk.Label(popup_win, text=f"(alebo {localhost_url})", font=("Segoe UI", 9), fg="#555").pack(pady=(0,3))
    else: tk.Label(popup_win, text="", font=("Segoe UI", 9)).pack(pady=(0,3)) # Placeholder for spacing
    ttk.Button(popup_win, text="Otvoriť v prehliadači", command=lambda u=server_url: webbrowser.open(u)).pack(pady=3)
    popup_win.update_idletasks() # Ensure dimensions are calculated
    scr_w, scr_h = popup_win.winfo_screenwidth(), popup_win.winfo_screenheight()
    win_w, win_h = popup_win.winfo_width(), popup_win.winfo_height()
    pos_x, pos_y = (scr_w // 2) - (win_w // 2), (scr_h // 2) - (win_h // 2)
    popup_win.geometry(f'{win_w}x{win_h}+{pos_x}+{pos_y}')
    popup_win.after(1000, lambda u=server_url: webbrowser.open(u)) # Open after a short delay
    popup_win.mainloop()

def run_web_server(host_addr, port_val):
    web_httpd = None
    try:
        HTTPServer.allow_reuse_address = True # Allow quick restarts
        web_httpd = HTTPServer((host_addr, port_val), SimpleRequestHandler)
        determined_ip = get_server_ip()
        print(f"--- Web server starting on {host_addr}:{port_val} (Accessible via http://{determined_ip}:{port_val}) ---")
        print("Press Ctrl+C in this console to stop the server."); web_httpd.serve_forever()
    except OSError as os_err:
         if os_err.errno in [98, 48, 10048]: # Common "Address already in use" codes
             print(f"\nERROR: Port {port_val} is already in use on {host_addr}.")
             messagebox.showerror("Server Error", f"Port {port_val} is already in use.\nClose other apps or change WEB_SERVER_PORT.")
         else:
             print(f"\nERROR: Could not start web server: {os_err}")
             messagebox.showerror("Server Error", f"Could not start web server on {port_val}.\nError: {os_err}")
         os._exit(1) # Force exit if server cannot start
    except KeyboardInterrupt: print("\nWeb server stopping (Ctrl+C).")
    except Exception as e_web_serv: print(f"\nUnexpected web server error: {e_web_serv}")
    finally:
        if web_httpd: web_httpd.server_close(); print("Web server closed.")

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Starting Leaderboard Application ---")
    load_correct_answers_config() # Load all config first
    load_leaderboard()

    root_serial_gui = tk.Tk(); root_serial_gui.title("Select Serial Port")
    try: num_avail_ports = len(list(serial.tools.list_ports.comports()))
    except: num_avail_ports = 0
    win_width_sel, win_height_sel = 400, 100 + max(1, num_avail_ports) * 30
    root_serial_gui.geometry(f"{win_width_sel}x{win_height_sel}")
    root_serial_gui.eval('tk::PlaceWindow . center'); root_serial_gui.attributes('-topmost', True)
    
    SERIAL_PORT = find_serial_port(root_serial_gui) # This function now handles its own mainloop

    if SERIAL_PORT:
        print(f"Selected serial port: {SERIAL_PORT}")
        serial_listen_thread = threading.Thread(target=serial_listener, name="SerialListenerThread", daemon=True)
        serial_listen_thread.start()
        print("Serial listener thread initiated.")

        web_server_thread_main = threading.Thread(target=run_web_server, args=(WEB_SERVER_HOST, WEB_SERVER_PORT), name="WebServerThread", daemon=True)
        web_server_thread_main.start()
        print("Web server thread initiating...")
        time.sleep(0.7) # Brief pause for server to start or fail

        ip_for_popup = get_server_ip()
        popup_thread_main = threading.Thread(target=show_ip_popup, args=(ip_for_popup, WEB_SERVER_PORT), name="PopupThread", daemon=True)
        popup_thread_main.start()

        print("--- Application is now running. Main thread will monitor sub-threads. ---")
        print("--- (Press Ctrl+C in console to attempt graceful shutdown of web server) ---")
        try:
            while True: # Keep main thread alive to catch Ctrl+C for server, and monitor threads
                if not serial_listen_thread.is_alive() and SERIAL_PORT: # Check only if port was selected
                    print("CRITICAL ERROR: Serial listener thread has died! Data from ESP32 will not be received.")
                    messagebox.showerror("Thread Error", "Serial listener thread stopped unexpectedly. Check console and restart.")
                    break 
                if not web_server_thread_main.is_alive():
                    print("CRITICAL ERROR: Web server thread has died!")
                    # run_web_server already shows a messagebox on bind error and exits.
                    # If it dies for another reason, this is a fallback.
                    messagebox.showerror("Thread Error", "Web server thread stopped unexpectedly. The leaderboard is down. Check console.")
                    break
                time.sleep(2) # Check status every 2 seconds
        except KeyboardInterrupt:
            print("\nCtrl+C detected in main thread. Initiating shutdown...")
        finally:
            print("--- Application Shutting Down Gracefully ---")
            # Threads are daemonic, they will exit when main thread exits.
            # run_web_server has its own finally block for server_close.
            # serial_listener has its own finally block for port_close.
    else:
        print("No serial port selected, or selection was cancelled. Exiting application.")
        # messagebox.showinfo("Exiting", "No serial port was selected. The application will now exit.") # Can be too intrusive if user just closes selection window

    print("--- Application Exit ---")
