# -*- coding: utf-8 -*-
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

# Konfigurácia
SERIAL_PORT = None
BAUD_RATE = 115200
WEB_SERVER_HOST = "0.0.0.0"  
WEB_SERVER_PORT = 8080
ADMIN_PASSWORD = "SPSIT"  
leaderboard_file = "leaderboard.json"
correct_answers_file = "correct_answers.json"

# Konfigurácia kategórií (UID)
CATEGORY1_UID_STR = "0xF30xC70x1A0x130x3D"
CATEGORY2_UID_STR = "0x8A0x8D0x570x540x04"
CATEGORY3_UID_STR = "0x120x9C0x190xFA0x6D"
CATEGORY_UIDS = {
    CATEGORY1_UID_STR: "Category1",
    CATEGORY2_UID_STR: "Category2",
    CATEGORY3_UID_STR: "Category3",
}
CATEGORY_DISPLAY_NAMES = {
    "Category1": "Kategória 1",
    "Category2": "Kategória 2",
    "Category3": "Kategória 3",
    "All Categories": "Všetky kategórie"
}
CATEGORY_NAMES_ADMIN = ["Kategória 1", "Kategória 2", "Kategória 3"]
CATEGORY_NAMES_CONFIG_KEYS = ["Category1", "Category2", "Category3"]
# Globálne premenné 
leaderboard_data = []  # Tabuľka načítaná zo súboru
correct_answers_config = {"penalty": 60, "categories": {
    "Category1": {}, "Category2": {}, "Category3": {}, "All Categories": {}
}} # Predvolená konfigurácia
PENALTY_PER_INCORRECT = correct_answers_config["penalty"] # Počiatočná hodnota penalizácie
NUM_QUESTIONS_PER_CATEGORY = 15

# GUI a výber sériového portu 
def find_serial_port(root):
    """Zobrazí okno Tkinter na výber sériového portu."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        messagebox.showerror("Chyba", "Nenašli sa žiadne sériové porty. Uistite sa, že je vaše ESP32 pripojené.", parent=root)
        root.destroy() # Zatvorí okno, ak sa nenájdu žiadne porty
        return None
    print("Dostupné sériové porty:")
    for i, (port, desc, hwid) in enumerate(ports):
        print(f"{i + 1}: {port} {desc} {hwid}")
    if len(ports) == 1:
        print(f"Automaticky vyberám jediný dostupný port: {ports[0].device}")
        root.destroy() # Zatvorí okno, keďže sme vybrali automaticky
        return ports[0].device

    # Ak je viacero portov, zobrazí dialóg na výber
    port_var = tk.StringVar()
    port_var.set(ports[0].device) # Predvolený výber
    selected_port_result = None

    def select_port():
        nonlocal selected_port_result
        selected_port = port_var.get()
        root.destroy()
        selected_port_result = selected_port

    ttk.Label(root, text="Prosím, vyberte sériový port ESP32:").pack(pady=(10, 5))
    for port in ports: # Vytvára možnosť výberu pre každý port
        ttk.Radiobutton(root, text=f"{port.device} ({port.description})", variable=port_var, value=port.device).pack(anchor=tk.W, padx=20)
    ttk.Button(root, text="Vybrať", command=select_port).pack(pady=10)
    root.protocol("WM_DELETE_WINDOW", root.destroy) # Umožní zatvorenie okna bez výberu
    root.mainloop()
    return selected_port_result

# Ukladanie tabuľky
def load_leaderboard():
    """Načíta údaje rebríčka zo súboru JSON, zabezpečuje existenciu potrebných polí."""
    global leaderboard_data
    try:
        if os.path.exists(leaderboard_file):
            with open(leaderboard_file, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    leaderboard_data = loaded_data
                    for entry in leaderboard_data:
                        entry["disqualified"] = entry.get("disqualified", False)
                        entry["original_time"] = entry.get("original_time", 0)
                        entry["answers"] = entry.get("answers", {}) # Pridá prázdny dict, ak chýba
                        entry["time"] = entry.get("time", entry.get("original_time", 0)) 
                        entry["penalty"] = entry.get("penalty", entry["time"] - entry["original_time"]) 
                    print("Rebríček načítaný zo súboru.")
                else:
                    print(f"Varovanie: {leaderboard_file} neobsahuje platný zoznam. Začínam odznova.")
                    leaderboard_data = []
        else:
            leaderboard_data = []
            print("Súbor rebríčka nebol nájdený, začínam s prázdnym rebríčkom.")
    except json.JSONDecodeError as e:
        print(f"Chyba pri dekódovaní súboru rebríčka ({leaderboard_file}): {e}. Začínam odznova.")
        leaderboard_data = []
    except Exception as e:
        print(f"Chyba pri načítavaní rebríčka: {e}. Začínam odznova.")
        leaderboard_data = []
    leaderboard_data.sort(key=lambda x: (x.get("disqualified", False), x.get("time", 0), x.get("penalty", 0)))

def save_leaderboard(leaderboard_to_save):
    """Uloží dané údaje rebríčka (vrátane odpovedí) do súboru JSON."""
    global leaderboard_data
    try:
        if not isinstance(leaderboard_to_save, list):
             print(f"Chyba: Pokus o uloženie dát, ktoré nie sú zoznamom, do rebríčka: {type(leaderboard_to_save)}")
             return 
        with open(leaderboard_file, "w", encoding="utf-8") as f:
            # Zabezpečí, že odpovede sú v uložených dátach
            json.dump(leaderboard_to_save, f, ensure_ascii=False, indent=4)
        leaderboard_data = leaderboard_to_save # Aktualizuje globálnu premennú po úspešnom uložení
        print("Rebríček uložený do súboru.")
    except Exception as e:
        print(f"Chyba pri ukladaní rebríčka: {e}")


# Logika bodovania 
def get_correct_answers_for_category(config, category_name):
    """Získa správne odpovedí {číslo_otázky_str: odpoveď} pre špecifickú kategóriu."""
    categories = config.get("categories", {})
    # Vráti odpovede pre špecifickú kategóriu, alebo prázdny dict, ak sa názov kategórie nenájde
    return categories.get(category_name, {})

def calculate_score(entry_answers, original_time, category, config): 
    # Vypočíta penalizáciu, výsledný čas a stav diskvalifikácie pre dané odpovede a konfiguráciu. 
    category_correct_answers = get_correct_answers_for_category(config, category)
    penalty_seconds = 0
    disqualified = False
    num_defined_questions = len(category_correct_answers)
    # Použije počet *definovaných* otázok pre kategóriu, ak je k dispozícii, inak predvolené
    expected_num_questions = num_defined_questions if num_defined_questions > 0 else NUM_QUESTIONS_PER_CATEGORY

    # Získa hodnotu penalizácie z poskytnutej konfigurácie, ak nie automaticky da 60 sekund
    penalty_per_incorrect = int(config.get("penalty", 60))

    # diskvalifikácia spočítá, koľko z *definovaných* otázok bolo zodpovedaných
    answered_defined_count = 0
    for q_num_str in category_correct_answers.keys():
        if q_num_str in entry_answers:
            answered_defined_count += 1

   # Diskvalifikácia: chýbajú odpovede na definované otázky ALEBO je celkový počet odpovedí menší ako očakávaný.
    if (num_defined_questions > 0 and answered_defined_count < num_defined_questions) or \
       len(entry_answers) < expected_num_questions :
        disqualified = True

    # Výpočet penalizácie prejde cez všetky otázky (až do NUM_QUESTIONS_PER_CATEGORY)
    for q_num in range(1, expected_num_questions + 1):
         question_num_str = str(q_num)
         submitted_answer = entry_answers.get(question_num_str)
         correct_answer = category_correct_answers.get(question_num_str) # Správna odpoveď *ak je definovaná*

         if submitted_answer is None: # Nezodpovedaná táto očakávaná otázka
             penalty_seconds += penalty_per_incorrect
             
         elif correct_answer is not None and submitted_answer != correct_answer: # Nesprávna odpoveď na definovanú otázku
             penalty_seconds += penalty_per_incorrect
           

    penalized_time = original_time + penalty_seconds
    return {
        "penalty": penalty_seconds,
        "time": penalized_time,
        "disqualified": disqualified
    }

# Správa tabuľky
def clear_leaderboard():
  #  Vymaže údaje rebríčka v pamäti aj v súbore.
    global leaderboard_data
    leaderboard_data = []
    save_leaderboard(leaderboard_data)
    print("Tabuľka vymazaná.")

def add_to_leaderboard(name, time_taken, answers, category):  
  #  Pridá/Aktualizuje výsledok účastníka, uloží surové odpovede a vypočíta počiatočné skóre. 
    global leaderboard_data, correct_answers_config # Použije aktuálnu konfiguráciu pre počiatočné pridanie

    name = name.strip()
    if not name:
        print(" Pokus o pridanie s prázdnym menom. Nepridáva sa.")
        return

    # Vypočíta počiatočné skóre na základe AKTUÁLNEJ konfigurácie pri pridávaní záznamu
    score_result = calculate_score(answers, time_taken, category, correct_answers_config)

    new_entry = {
        "name": name,
        "original_time": time_taken,     
        "category": category,           
        "answers": answers,               
        "time": score_result["time"],           
        "penalty": score_result["penalty"],        
        "disqualified": score_result["disqualified"]  
    }

    # Skontroluje, či záznam s rovnakým menom už existuje
    existing_entry_index = -1
    current_leaderboard = list(leaderboard_data) 
    for index, entry in enumerate(current_leaderboard):
        # porovnava meno 
        if entry.get("name", "").strip() == new_entry["name"]:
            existing_entry_index = index
            break

    # Rozhodne, či pridať, nahradiť alebo zahodiť nový záznam
    should_update = False
    if existing_entry_index != -1:
        # Účastník existuje, porovná nový záznam s existujúcim
        existing_entry = current_leaderboard[existing_entry_index]
        # Definuje stav diskvalifikácie, potom nižší čas, potom nižšia penalizácia
        if (new_entry["disqualified"], new_entry["time"], new_entry["penalty"]) < \
           (existing_entry.get("disqualified", True), existing_entry.get("time", float('inf')), existing_entry.get("penalty", float('inf'))): # Použije .get pre bezpečnosť
            print(f"Nový záznam pre '{new_entry['name']}' je lepší ako existujúci, nahrádzam.")
            current_leaderboard[existing_entry_index] = new_entry # Nahradí v kópii
            should_update = True
        else:
            print(f"Nový záznam pre '{new_entry['name']}' nie je lepší ako existujúci ({format_time(new_entry['time'], new_entry['disqualified'])}) vs existujúci ({format_time(existing_entry.get('time',0), existing_entry.get('disqualified', False))}), zahadzujem.")
            return 
    else:
        # Účastník je nový, pridá do tabuľky
        print(f"Pridávam nový záznam pre '{new_entry['name']}'.")
        current_leaderboard.append(new_entry)
        should_update = True

    # Ak sme pridali alebo nahradili záznam, znova zoradí a uloží
    if should_update:
        # Znovu zoradí celý rebríček
        current_leaderboard.sort(key=lambda x: (x.get("disqualified", False), x.get("time", 0), x.get("penalty", 0)))
        save_leaderboard(current_leaderboard)
        print(f"Rebríček aktualizovaný. Záznam: Meno={new_entry['name']}, Výsledný čas={format_time(new_entry['time'], new_entry['disqualified'])}, Kategória={category}, Diskvalifikovaný={new_entry['disqualified']}")

def recalculate_and_sort_leaderboard():
  #   Prepočíta skóre pre VŠETKY záznamy na základe correct_answers_config a potom uloží aktualizovaný a zoradený rebríček. 
    global leaderboard_data, correct_answers_config
    print("Prepočítavam všetky skóre rebríčka na základe aktuálnej konfigurácie...")
    updated_leaderboard = []
    current_config = dict(correct_answers_config)
    # pristupije cez kópiu dát rebríčka, aby sa predišlo modifikácii zoznamu počas zapisovania
    for entry in list(leaderboard_data):
        # Potrebuje original_time, answers a category zo záznamu
        original_time = entry.get("original_time", 0)
        entry_answers = entry.get("answers", {})
        category = entry.get("category", "All Categories") 
        name = entry.get("name", "N/A")

        if not entry_answers:
            print(f"Varovanie: Záznam pre '{name}' (Kategória: {category}) nemá uložené žiadne odpovede. Nie je možné prepočítať skóre. Ponechávam existujúce skóre.")
            # Ponechá existujúci záznam tak, ako je, ak nie sú uložené žiadne odpovede
            updated_entry = entry
        else:
            # Prepočíta skóre pomocou pomocnej funkcie a aktuálnej konfigurácie
            new_score = calculate_score(entry_answers, original_time, category, current_config)
            # Aktualizuje záznam novým skóre (čas/penalizácia/diskvalifikácia).
            updated_entry = {
                "name": name,
                "original_time": original_time,
                "category": category,
                "answers": entry_answers, 
                "time": new_score["time"],
                "penalty": new_score["penalty"],
                "disqualified": new_score["disqualified"]
            }
        updated_leaderboard.append(updated_entry)

    # Zoradí novo zoradený rebríček na základe aktualizovaných skóre
    updated_leaderboard.sort(key=lambda x: (x.get("disqualified", False), x.get("time", 0), x.get("penalty", 0)))

    save_leaderboard(updated_leaderboard)
    print("zoradenie a uloženie rebríčka dokončené.")

# --- Formátovanie a generovanie HTML/CSV ---
def format_time(seconds, disqualified=False):
    """Formátuje sekundy na reťazec HH:MM:SS, voliteľne pridáva predponu 'D: '."""
    if not isinstance(seconds, (int, float)) or seconds < 0: seconds = 0 # Zabezpečí, že čas je nezáporné číslo
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    time_str = "{:02d}:{:02d}:{:02d}".format(hours, minutes, secs)
    # Pridá predponu "D: " ak je diskvalifikovany
    return f"D: {time_str}" if disqualified else time_str

def generate_leaderboard_csv(leaderboard_data_to_export):
    """Generuje CSV dát z dát rebríčka."""
    csv_data = "Poradie;Meno;Kategória;Pôvodný Čas;Penalizácia;Výsledný čas;Status\n"
    for i, entry in enumerate(leaderboard_data_to_export):
        # Použije .get s predvolenými hodnotami pre bezpečnosť
        original_time_sec = entry.get("original_time", 0)
        penalty_sec = entry.get("penalty", 0)
        final_time_sec = entry.get("time", 0)
        category_display = CATEGORY_DISPLAY_NAMES.get(entry.get("category", "N/A"), entry.get("category", "N/A"))
        disqualified = entry.get("disqualified", False)
        status = "Diskvalifikovaný" if disqualified else "Kvalifikovaný"
        original_time_str = format_time(original_time_sec)
        penalty_time_str = format_time(penalty_sec)
        final_time_str = format_time(final_time_sec, disqualified)
        safe_name = entry.get('name', 'N/A').replace(';', ',')
        csv_data += (
            f"{i + 1};{safe_name};{category_display};"
            f"{original_time_str};{penalty_time_str};"
            f"{final_time_str};{status}\n"
        )
    return csv_data

# generate_leaderboard_html 
def generate_leaderboard_html(leaderboard, selected_category="All Categories"):
    """Generuje hlavnú štruktúru HTML stránky pre rebríček."""
    # Tlačidlá na výber kategórie
    category_buttons_html = '<div style="text-align: center; margin-bottom: 20px;">\n'
    all_categories = list(CATEGORY_DISPLAY_NAMES.keys()) 
    for cat_key in all_categories:
        display_name = CATEGORY_DISPLAY_NAMES[cat_key]
        # Skontroluje, či aktuálne tlačidlo zodpovedá vybranej kategórii
        is_active = 'active' if cat_key == selected_category else ''
        category_buttons_html += f"""
            <form action="/" method="GET" style="display: inline;">
                <input type="hidden" name="category" value="{cat_key}">
                <button type="submit" class="button-link category-button {is_active}">{display_name}</button>
            </form>"""
    category_buttons_html += "\n</div>"
 # mainpage
    html_style = f"""
    <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8f9fa; color: #343a40; margin: 0; padding: 20px; line-height: 1.6; }}
    .container {{ width: 90%; max-width: 950px; margin: 20px auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }}
    h1 {{ text-align: center; color: #0056b3; margin-bottom: 30px; font-weight: 600; }}
    .header-controls {{ position: fixed; top: 10px; right: 20px; z-index: 1000;}} 
    .button-link {{ display: inline-block; padding: 10px 20px; margin: 5px 5px; /* Pridaný vertikálny okraj */ background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; font-size: 0.95em; transition: background-color 0.3s ease, transform 0.1s ease; border: none; cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    .button-link:hover {{ background-color: #0056b3; transform: translateY(-1px); }}
    .button-link:active {{ transform: translateY(0px); }}
    .button-link.admin {{ background-color: #28a745; }}
    .button-link.admin:hover {{ background-color: #218838; }}
    .category-button {{ background-color: #6c757d; }} /* Sivá pre tlačidlá kategórií */
    .category-button:hover {{ background-color: #5a6268; }}
    .category-button.active {{ background-color: #007bff; font-weight: bold; box-shadow: 0 0 8px rgba(0, 123, 255, 0.5); }} /* Modrá a žiara pre aktívnu kategóriu */
    table {{ border-collapse: collapse; width: 100%; margin: 25px auto; background-color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.05); font-size: 0.95em; }}
    th, td {{ border: 1px solid #dee2e6; padding: 10px 12px; text-align: left; vertical-align: middle; }}
    th {{ background-color: #e9ecef; color: #495057; font-weight: 600; white-space: nowrap; }}
    tr:nth-child(even) {{ background-color: #f8f9fa; }}
    tr:hover {{ background-color: #e9ecef; }} /* Mierne tmavšie pri prejdení myšou */
    #leaderboard {{ display: flex; justify-content: center; min-height: 100px; /* Zabráni crashnutiu, keď je prázdne */ }}
    #leaderboard table {{ width: 100%; }}
    .disqualified td {{ color: #dc3545; /* Červený text */ font-style: italic; background-color: #fdf1f2; /* Svetlejšie červené pozadie */ }}
    .loading-placeholder {{ text-align: center; padding: 40px; color: #6c757d; }}
    </style>
    """
    
    selected_category_display = CATEGORY_DISPLAY_NAMES.get(selected_category, selected_category)
    html_script_template = """
    <script>
    function refreshLeaderboard() {
        var xhttp = new XMLHttpRequest();
        xhttp.onreadystatechange = function() {
            if (this.readyState == 4) { // Požiadavka dokončená
                if (this.status == 200) { // Úspech
                    try {
                        document.getElementById("leaderboard").innerHTML = this.responseText;
                    } catch (e) {
                        console.error("Chyba pri aktualizácii HTML rebríčka:", e);
                        // Záloha alebo zobrazenie chyby v prípade potreby
                    }
                } else {
                    // Spracovanie chýb (napr. zobrazenie chybovej správy)
                    console.error("Nepodarilo sa obnoviť rebríček. Stav: " + this.status);
                    // Voliteľne zobraziť správu v oblasti zástupného symbolu
                    // document.getElementById("leaderboard").innerHTML = '<p class="loading-placeholder">Chyba pri načítaní tabuľky.</p>';
                }
            }
        };
        const urlParams = new URLSearchParams(window.location.search);
        const category = urlParams.get('category') || 'All Categories'; // Predvolená hodnota, ak nie je prítomná
        // Pridá parameter na obídenie cache, aby sa zabránilo zastaraným dátam
        const cacheBust = new Date().getTime();
        xhttp.open("GET", "/leaderboard_table?category=" + encodeURIComponent(category) + "&t=" + cacheBust, true);
        xhttp.setRequestHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
        xhttp.setRequestHeader('Pragma', 'no-cache');
        xhttp.setRequestHeader('Expires', '0');
        xhttp.send();
    }

    // Spustí sa pri počiatočnom načítaní a nastaví interval
    document.addEventListener('DOMContentLoaded', function() {
        // Počiatočné načítanie môže byť mierne oneskorené výpočtom, takže najprv zobrazí zástupný symbol
        document.getElementById("leaderboard").innerHTML = '<p class="loading-placeholder">Načítavam tabuľku...</p>';
        refreshLeaderboard(); // Získanie dát pri počiatočnom načítaní
        setInterval(refreshLeaderboard, 10000); // Obnovuje každých 10 sekúnd
    });
    </script>
    """

    #  cela HTML stránka
    html_content = f"""
    <!DOCTYPE html>
    <html lang="sk">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tabuľka Výsledkov - {selected_category_display}</title>
        {html_style}
        {html_script_template}
    </head>
    <body>
        <div class="header-controls">
            <a href="/admin" class="button-link admin">Admin</a>
        </div>
        <div class="container">
            <h1>Tabuľka Výsledkov</h1>
            {category_buttons_html}
            <div id="leaderboard">
                 <p class="loading-placeholder">Načítavam tabuľku...</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content

#generate_leaderboard_table_html 
def generate_leaderboard_table_html(leaderboard_to_display):
    """Generuje iba časť HTML tabuľky """
    table_html = """
    <table>
        <thead>
            <tr>
                <th>Poradie</th>
                <th>Meno</th>
                <th>Kategória</th>
                <th>Pôvodný Čas</th>
                <th>Penalizácia</th>
                <th>Výsledný čas</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
    """

    if not leaderboard_to_display:
        table_html += '<tr><td colspan="7" style="text-align:center; padding: 20px; color: #6c757d;">Zatiaľ žiadne výsledky v tejto kategórii.</td></tr>'
    else:
        for i, entry in enumerate(leaderboard_to_display):
            original_time_sec = entry.get("original_time", 0)
            penalty_sec = entry.get("penalty", 0)
            final_time_sec = entry.get("time", 0)
            category_display = CATEGORY_DISPLAY_NAMES.get(entry.get("category", "N/A"), entry.get("category", "N/A"))
            disqualified = entry.get("disqualified", False)
            status = "Diskvalifikovaný" if disqualified else "Kvalifikovaný"
            row_class = "disqualified" if disqualified else "" 

            # Formátovanie času
            original_time_str = format_time(original_time_sec)
            penalty_time_str = format_time(penalty_sec)
            final_time_str = format_time(final_time_sec, disqualified)
            safe_name = entry.get('name', 'N/A') 

            table_html += f"""
            <tr class="{row_class}">
                <td>{i + 1}</td>
                <td>{safe_name}</td>
                <td>{category_display}</td>
                <td>{original_time_str}</td>
                <td>{penalty_time_str}</td>
                <td>{final_time_str}</td>
                <td>{status}</td>
            </tr>
            """

    table_html += "</tbody></table>"
    return table_html

# generate_admin_html 
def generate_admin_html(config):
    """Generuje HTML stránku administrátorskej konfigurácie."""
    penalty = config.get("penalty", 60)
    category_names = CATEGORY_NAMES_ADMIN
    category_config_keys = CATEGORY_NAMES_CONFIG_KEYS

    admin_page_style = f"""
    <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8f9fa; color: #343a40; margin: 0; padding: 20px; }}
    .container {{ width: 90%; max-width: 1200px; margin: 20px auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }}
    h1, h2 {{ text-align: center; color: #0056b3; margin-bottom: 25px; font-weight: 600;}}
    h2 {{ margin-top: 40px; border-bottom: 1px solid #dee2e6; padding-bottom: 10px; }}
    h3 {{ text-align: center; color: #17a2b8; margin-bottom: 15px; font-weight: 600; }} /* Info farba */
    label {{ display: block; margin-top: 12px; font-weight: 600; margin-bottom: 5px; }}
    input[type="number"], select, input[type="password"] {{ width: 100%; padding: 10px; margin-top: 5px; margin-bottom: 15px; border: 1px solid #ced4da; border-radius: 5px; box-sizing: border-box; font-size: 1em; background-color: #fff; }}
    select {{ appearance: none; -webkit-appearance: none; -moz-appearance: none; background-image: url('data:image/svg+xml;utf8,<svg fill="%23495057" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M7 10l5 5 5-5z"/><path d="M0 0h24v24H0z" fill="none"/></svg>'); background-repeat: no-repeat; background-position: right 10px center; background-size: 1em; padding-right: 2.5em; }}
    .button-base {{ display: inline-block; width: auto; min-width: 180px; padding: 12px 25px; margin: 10px 5px; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em; font-weight: 500; transition: background-color 0.3s ease, box-shadow 0.2s ease, transform 0.1s ease; text-align: center; box-sizing: border-box; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    .button-base:hover {{ filter: brightness(95%); box-shadow: 0 4px 8px rgba(0,0,0,0.15); transform: translateY(-1px); }}
    .button-base:active {{ transform: translateY(0); }}
    .button-save {{ background-color: #28a745; }} /* Zelená */
    .button-back {{ background-color: #6c757d; }} /* Sivá */
    .button-export {{ background-color: #ffc107; color: #343a40; }} /* Žltá */
    .button-reset {{ background-color: #dc3545; }} /* Červená */
    .button-container {{ text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; }}
    .reset-section {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;}}
    .reset-section p {{ color: #dc3545; font-weight: bold; }}
    .form-group {{ margin-bottom: 15px; /* Zmenšený spodný okraj */ padding: 0 10px; }}
    .category-container {{ display: flex; justify-content: space-around; flex-wrap: wrap; gap: 25px; margin-top: 20px; }}
    .category-section {{ flex: 1; min-width: 280px; max-width: 31%; border: 1px solid #dee2e6; padding: 20px; border-radius: 8px; background-color: #f8f9fa; box-shadow: inset 0 1px 3px rgba(0,0,0,0.05); }}
    .category-answers-box {{
        margin-top: 10px;
        padding-right: 5px; /* Ponechá malý padding */
    }}
    /* Responzívne úpravy */
    @media (max-width: 992px) {{
        .category-section {{ max-width: 48%; min-width: 250px; }}
    }}
    @media (max-width: 768px) {{
        .category-section {{ max-width: 100%; min-width: unset; }}
    }}
    </style>
    """

    # --- Obsah HTML administrátorskej stránky ---
    html_content = f"""
    <!DOCTYPE html>
    <html lang="sk">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Admin Nastavenia</title>
        {admin_page_style}
        <script>
            function checkPasswordAndReset() {{
                var passwordInput = document.getElementById('resetPassword');
                var password = passwordInput.value;
                if (!password) {{
                    alert('Prosím, zadajte admin heslo.');
                    passwordInput.focus(); // Zameria pole pre heslo
                    return;
                }}
                // Použije striktné porovnanie
                if (password === '{ADMIN_PASSWORD}') {{
                    // Dvojité potvrdenie
                    if (confirm('Naozaj chcete vymazať VŠETKY výsledky z tabuľky? Táto akcia je NEVRATNÁ!')) {{
                        if (confirm('Posledné varovanie: Ste si úplne istý/á?')) {{
                            var xhr = new XMLHttpRequest();
                            xhr.open('POST', '/admin_reset', true);
                            xhr.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
                            xhr.onload = function () {{
                                if (xhr.status >= 200 && xhr.status < 300) {{
                                    alert('Resetovanie tabuľky prebehlo úspešne!');
                                    window.location.reload(); // Znovu načíta stránku na zobrazenie zmien
                                }} else {{
                                    alert('Chyba pri resetovaní tabuľky. Skúste znova neskôr. Stav: ' + xhr.status + ' ' + xhr.statusText);
                                }}
                            }};
                            xhr.onerror = function () {{
                                alert('Chyba siete pri pokuse o resetovanie tabuľky.');
                            }};
                            xhr.send('password=' + encodeURIComponent(password));
                        }}
                    }}
                }} else {{
                    alert('Nesprávne heslo. Reset zamietnutý.');
                }}
                // Vymaže pole pre heslo bez ohľadu na úspech/neúspech
                passwordInput.value = '';
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <h1>Admin - Správne odpovede a penalizácia</h1>
            <form action="/save_answers" method="post">
                <div class="form-group" style="max-width: 400px; margin-left: auto; margin-right: auto;">
                    <label for="penalty">Penalizácia za nesprávnu/nevyplnenú odpoveď (sekundy):</label>
                    <input type="number" id="penalty" name="penalty" value="{penalty}" min="0" step="1" required>
                </div>

                <h2>Správne odpovede podľa kategórií</h2>
                <p style="text-align:center; font-size: 0.9em; color: #6c757d;">Nastavte správne odpovede pre každú otázku. Otázky bez vybranej správnej odpovede nebudú penalizované.</p>
                <div class="category-container">
    """

    # výber odpovedí pre každú kategóriu
    for i, category_key in enumerate(category_config_keys):
        category_name = category_names[i]
        category_answers = config.get("categories", {}).get(category_key, {})
        html_content += f"""
                    <div class="category-section">
                        <h3>{category_name}</h3>
                        <div class="category-answers-box">
        """
        # Cyklus až do NUM_QUESTIONS_PER_CATEGORY 
        for q_num in range(1, NUM_QUESTIONS_PER_CATEGORY + 1):
            question_num_str = str(q_num)
            current_answer = category_answers.get(question_num_str, "") 
            html_content += f"""
                            <div class="form-group">
                                <label for="answer_{category_key}_{q_num}">Otázka {q_num}:</label>
                                <select id="answer_{category_key}_{q_num}" name="answer_{category_key}_{q_num}">
            """
            # Možnosti: A, B, C, D a prázdna hodnota pre "Nenastavené"
            answer_options = ["", "A", "B", "C", "D"]
            option_texts = ["-- Nevybraté --", "A", "B", "C", "D"]
            for option_value, option_text in zip(answer_options, option_texts):
                selected = "selected" if option_value == current_answer else ""
                html_content += f'<option value="{option_value}" {selected}>{option_text}</option>'
            html_content += """
                                </select>
                            </div>
            """
        html_content += """
                        </div>
                    </div>
        """

    html_content += """
                </div>
                <div class="button-container">
                    <button type="submit" class="button-base button-save">Uložiť nastavenia a PREPOČÍTAŤ VÝSLEDKY</button>
                </div>
            </form>

            <div class="button-container">
                 <h2>Export výsledkov (CSV pre Excel)</h2>
                 <a href="/leaderboard_excel" class="button-base button-export" download="leaderboard_all_categories.csv">Exportovať Všetky Kategórie</a>
                 <a href="/leaderboard_excel_category?category=Category1" class="button-base button-export" download="leaderboard_Kategoria_1.csv">Exportovať Kategóriu 1</a>
                 <a href="/leaderboard_excel_category?category=Category2" class="button-base button-export" download="leaderboard_Kategoria_2.csv">Exportovať Kategóriu 2</a>
                 <a href="/leaderboard_excel_category?category=Category3" class="button-base button-export" download="leaderboard_Kategoria_3.csv">Exportovať Kategóriu 3</a>
            </div>


            <div class="reset-section">
                <h2>Reset tabuľky</h2>
                 <p>Táto akcia permanentne vymaže všetky uložené výsledky!</p>
                <div class="form-group" style="max-width: 300px; margin-left: auto; margin-right: auto;">
                    <label for="resetPassword">Admin Heslo pre Reset:</label>
                    <input type="password" id="resetPassword" name="resetPassword" required autocomplete="new-password">
                </div>
                <div class="button-container" style="border-top: none; padding-top: 0;">
                    <button type="button" onclick="checkPasswordAndReset()" class="button-base button-reset">Resetovať Celú Tabuľku</button>
                </div>
            </div>


            <div class="button-container">
                <a href="/" class="button-base button-back">Späť na Hlavnú Tabuľku</a>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content


# Pomocné a konfiguračné funkcie
def get_category_name_from_uid_str(uid_str):
    return CATEGORY_UIDS.get(uid_str, "All Categories") 

def load_correct_answers_config():
    """Načíta konfiguráciu správnych odpovedí a penalizácie zo súboru JSON."""
    global correct_answers_config, PENALTY_PER_INCORRECT
    default_config = {
        "penalty": 60,
        "categories": {key: {} for key in CATEGORY_NAMES_CONFIG_KEYS + ["All Categories"]}
    }

    try:
        if os.path.exists(correct_answers_file):
            with open(correct_answers_file, "r", encoding="utf-8") as f:
                config = json.load(f)
                if isinstance(config, dict) and "penalty" in config and isinstance(config.get("categories"), dict):
                    correct_answers_config = config
                    for key in CATEGORY_NAMES_CONFIG_KEYS:
                        if key not in correct_answers_config["categories"]:
                             correct_answers_config["categories"][key] = {}
                    if "All Categories" not in correct_answers_config["categories"]:
                         correct_answers_config["categories"]["All Categories"] = {}
                    # Zabezpečí, že penalizácia je celé číslo
                    PENALTY_PER_INCORRECT = int(correct_answers_config.get("penalty", 60))
                    correct_answers_config["penalty"] = PENALTY_PER_INCORRECT 
                    print("Konfigurácia správnych odpovedí úspešne načítaná.")
                else:
                    print(f"Varovanie: Neplatná štruktúra v {correct_answers_file}. Používam predvolenú konfiguráciu.")
                    correct_answers_config = default_config
                    PENALTY_PER_INCORRECT = default_config["penalty"]
        else:
            print(f"{correct_answers_file} nenájdený. Používam predvolenú konfiguráciu a vytváram súbor.")
            correct_answers_config = default_config
            PENALTY_PER_INCORRECT = default_config["penalty"]
            save_correct_answers_config(correct_answers_config) # Uloží predvolenú konfiguráciu pri prvom spustení
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"Chyba pri načítavaní alebo parsovaní {correct_answers_file}: {e}. Používam predvolenú konfiguráciu.")
        correct_answers_config = default_config
        PENALTY_PER_INCORRECT = default_config["penalty"]
    except Exception as e:
        print(f"Neočakávaná chyba pri načítavaní konfigurácie správnych odpovedí: {e}. Používam predvolenú konfiguráciu.")
        correct_answers_config = default_config
        PENALTY_PER_INCORRECT = default_config["penalty"]

def save_correct_answers_config(config_to_save):
    """Uloží konfiguráciu správnych odpovedí a penalizácie do jej súboru JSON."""
    global correct_answers_config, PENALTY_PER_INCORRECT
    try:
        config_to_save["penalty"] = int(config_to_save.get("penalty", 60))

        with open(correct_answers_file, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, ensure_ascii=False, indent=4)
        print("Konfigurácia správnych odpovedí a penalizácie uložená do súboru.")
        # Aktualizuje globálne premenné *po* úspešnom uložení
        correct_answers_config = config_to_save
        PENALTY_PER_INCORRECT = correct_answers_config["penalty"]
    except Exception as e:
        print(f"Chyba pri ukladaní konfigurácie správnych odpovedí: {e}")

def filter_leaderboard_by_category(leaderboard, category):
    """Filtruje zoznam rebríčka tak, aby obsahoval iba záznamy pre špecifikovanú kategóriu."""
    if category == "All Categories" or not category:
        return leaderboard 
    else:
        return [entry for entry in leaderboard if entry.get("category") == category]

# počúvanie sériového portu 
def serial_listener():
    """Počúva prichádzajúce JSON dáta na vybranom sériovom porte a spracováva opätovné pripojenie."""
    global leaderboard_data, correct_answers_config 
    serial_connection = None 

    if SERIAL_PORT is None:
        print("Chyba: Sériový port nebol vybraný. Vlákno na počúvanie sériového portu nemôže začať.")
        return # Ukončí, ak port nebol vybraný

    while True: # pokus o opätovné pripojenie, ak spojenie padne
        try:
            print(f"Pokúšam sa pripojiť k sériovému portu: {SERIAL_PORT} pri {BAUD_RATE} baud...")
            serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            print(f"Úspešne pripojené. Počúvam na {SERIAL_PORT}...")
            buffer = ""
            while True: # cyklus na čítanie dát
                try:
                    if serial_connection.in_waiting > 0:
                        data_bytes = serial_connection.read(serial_connection.in_waiting)
                        buffer += data_bytes.decode('utf-8', errors='ignore') 

                        # Spracuje riadky (JSON objekty) 
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if not line: continue 

                            try:
                                json_data = json.loads(line)

                                if isinstance(json_data, dict) and \
                                   "name" in json_data and isinstance(json_data["name"], str) and \
                                   "time" in json_data and isinstance(json_data["time"], (int, float)) and \
                                   "answers" in json_data and isinstance(json_data["answers"], dict) and \
                                   "category_uid" in json_data and isinstance(json_data["category_uid"], str):

                                    name = json_data["name"].strip() 
                                    time_taken = float(json_data["time"])
                                    answers_data = json_data["answers"] 
                                    category_uid_str = json_data["category_uid"]
                                    category_name = get_category_name_from_uid_str(category_uid_str)

                                    if not name:
                                        print("Varovanie: Prijatý záznam s prázdnym menom. Preskakujem.")
                                        continue
                                    # Zavolá add_to_leaderboard, ktorá uloží surové odpovede, vypočíta počiatočné skóre, spracuje duplikáty a uloží
                                    add_to_leaderboard(name, time_taken, answers_data, category_name)
                                else:
                                    print(f"Varovanie: Prijatý JSON s chýbajúcimi/neplatnými poľami: {json_data}")
                            except json.JSONDecodeError as e:
                                print(f"Chyba pri dekódovaní JSON zo sériového riadku: {e}. Riadok: '{line}'")
                            except Exception as e: 
                                print(f"Chyba pri spracovaní prijatých sériových dát: {e}. Riadok: '{line}'")
                    time.sleep(0.05)

                except serial.SerialException as e: # Zachytí errory (napr. odpojené zariadenie)
                     print(f"Sériová chyba počas čítania: {e}. Pokúšam sa znovu pripojiť...")
                     raise e 

        except serial.SerialException as e:
            print(f"Chyba pripojenia sériového portu: {e}. Pokúšam sa znovu pripojiť o 5 sekúnd...")
            if serial_connection and serial_connection.is_open:
                try:
                    serial_connection.close()
                except Exception as close_err:
                    print(f"Chyba pri zatváraní sériového portu: {close_err}")
            serial_connection = None # Zabezpečí, že je None, aby sme sa pokúsili o opätovné vytvorenie
            time.sleep(5)
        except KeyboardInterrupt:
            print("Vlákno na počúvanie sériového portu zastavené používateľom (KeyboardInterrupt).")
            break 
        except Exception as e:
            print(f"Neočakávaná chyba vo vlákne na počúvanie sériového portu: {e}. Skúšam znova o 10 sekúnd...")
            if serial_connection and serial_connection.is_open:
                 try:
                     serial_connection.close()
                 except Exception as close_err:
                     print(f"Chyba pri zatváraní sériového portu: {close_err}")
            serial_connection = None
            time.sleep(10) # Počká dlhšie pri neočakávaných chybách

    if serial_connection and serial_connection.is_open:
        serial_connection.close()
        print("Sériové pripojenie zatvorené pri ukončení vlákna na počúvanie.")

# --- HTTP Request Handler ---
class SimpleRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        global leaderboard_data, correct_answers_config # Umožní prístup k globálnym premenným
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        query_params = urllib.parse.parse_qs(parsed_path.query)

        try:
            if path == "/":
                selected_category = query_params.get("category", ["All Categories"])[0]
                current_leaderboard = list(leaderboard_data)
                filtered_leaderboard = filter_leaderboard_by_category(current_leaderboard, selected_category)
                html = generate_leaderboard_html(filtered_leaderboard, selected_category)
                self.send_html_response(html)

            elif path == "/admin":
                admin_html = generate_admin_html(dict(correct_answers_config))
                self.send_html_response(admin_html)
 
            elif path == "/leaderboard_table":
                selected_category = query_params.get("category", ["All Categories"])[0]
                current_leaderboard = list(leaderboard_data) # Získa aktuálny stav
                filtered_leaderboard = filter_leaderboard_by_category(current_leaderboard, selected_category)
                table_html = generate_leaderboard_table_html(filtered_leaderboard)
                
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate") # Zabezpečí čerstvé dáta pre AJAX
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(table_html.encode("utf-8"))
            
            elif path == "/leaderboard_excel":
                current_leaderboard = list(leaderboard_data)
                csv_data = generate_leaderboard_csv(current_leaderboard)
                self.send_csv_response(csv_data, "leaderboard_all_categories.csv")

            elif path == "/leaderboard_excel_category":
                category_name = query_params.get("category", [""])[0]
                if not category_name or category_name not in CATEGORY_DISPLAY_NAMES:
                    self.send_error(400, "Bad Request", "Neplatný alebo chýbajúci parameter 'category'")
                    return
                current_leaderboard = list(leaderboard_data)
                filtered_leaderboard = filter_leaderboard_by_category(current_leaderboard, category_name)
                display_name = CATEGORY_DISPLAY_NAMES.get(category_name, category_name).replace(' ', '_')
                filename = f"leaderboard_{display_name}.csv"
                csv_data = generate_leaderboard_csv(filtered_leaderboard)
                self.send_csv_response(csv_data, filename)
    
            else:
                self.send_error(404, "Not Found", f"Zdroj '{path}' nebol nájdený.")
        except Exception as e:
             print(f"Chyba pri spracovaní GET požiadavky {self.path}: {e}")

             if not self.wfile.closed:
                 try:
                     self.send_error(500, "Internal Server Error", "Vyskytla sa chyba pri spracovaní vašej požiadavky.")
                 except Exception as send_err:
                     print(f"Chyba pri odosielaní odpovede 500: {send_err}")


    def do_POST(self):
        path = self.path
        try:
            if path == "/save_answers":
                self.handle_save_answers() 
           
            elif path == "/admin_reset":
                self.handle_admin_reset()

            # path: Pridanie záznamu (Zakázané cez HTTP - Použiť sériový port)
            elif path == "/add":
                self.send_error(405, "Method Not Allowed", "Záznamy súť pridávané cez sériové pripojenie, nie HTTP POST.")

            # Trasa: Nenájdené / Metóda nie je povolená pre ostatné POST požiadavky
            else:
                self.send_error(405, "Method Not Allowed", f"Metóda POST nie je podporovaná pre '{path}'.")
        except Exception as e:
             print(f"Chyba pri spracovaní POST požiadavky {self.path}: {e}")
             if not self.wfile.closed:
                 try:
                     self.send_error(500, "Internal Server Error", "Vyskytla sa chyba pri spracovaní vašej požiadavky.")
                 except Exception as send_err:
                     print(f"Chyba pri odosielaní odpovede 500: {send_err}")

    def handle_save_answers(self):
        """Spracuje POST požiadavku na uloženie administrátorskej konfigurácie A spúšťa prepočítanie."""
        global correct_answers_config 
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 10 * 1024: # Obmedzí veľkosť požiadavky 
                 self.send_error(413, "Payload Too Large")
                 return
            post_data = self.rfile.read(content_length).decode('utf-8')
            form_data = urllib.parse.parse_qs(post_data)

            updated_config = {
                "penalty": 60, # Predvolená penalizácia
                "categories": {}
            }
            try:
                penalty_str = form_data.get("penalty", ["60"])[0]
                penalty_val = int(penalty_str)
                updated_config["penalty"] = max(0, penalty_val) 
            except (ValueError, IndexError, TypeError):
                print("Varovanie: Prijatá neplatná hodnota penalizácie. Používam predvolenú 60.")
                updated_config["penalty"] = 60

            # Aktualizuje odpovede pre každú kategóriu
            for category_key in CATEGORY_NAMES_CONFIG_KEYS:
                updated_answers = {}
                for q_num in range(1, NUM_QUESTIONS_PER_CATEGORY + 1):
                    answer_key = f"answer_{category_key}_{q_num}"
                    answer_list = form_data.get(answer_key, [""])
                    answer = urllib.parse.unquote_plus(answer_list[0]).strip() if answer_list else ""
                    # Uloží iba platné odpovede ("A", "B", "C", "D") 
                    if answer in ["A", "B", "C", "D"]:
                        updated_answers[str(q_num)] = answer
                    # Neukladáme prázdny reťazec v JSONe
                updated_config["categories"][category_key] = updated_answers
            if "All Categories" not in updated_config["categories"]:
                updated_config["categories"]["All Categories"] = {}

            save_correct_answers_config(updated_config)
            recalculate_and_sort_leaderboard()
            self.send_redirect_response("/admin")

        except Exception as e:
            print(f"Chyba pri spracovaní save_answers POST: {e}")
            if not self.wfile.closed:
                 try:
                     self.send_error(500, "Internal Server Error", "Nepodarilo sa uložiť konfiguráciu alebo prepočítať skóre.")
                 except Exception as send_err:
                      print(f"Chyba pri odosielaní odpovede 500: {send_err}")

    def handle_admin_reset(self):
        """Spracuje POST požiadavku na resetovanie rebríčka po kontrole hesla."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 1024: 
                 self.send_error(413, "Payload Too Large")
                 return
            post_data = self.rfile.read(content_length).decode('utf-8')
            form_data = urllib.parse.parse_qs(post_data)
            password_attempt = form_data.get("password", [""])[0]

            if password_attempt == ADMIN_PASSWORD:
                clear_leaderboard() # Táto funkcia teraz spracováva uloženie prázdneho zoznamu
                self.send_response(204) 
                self.end_headers()
                print("Rebríček úspešne resetovaný cez administrátorskú požiadavku.")
            else:
                print(f"Neúspešný pokus o resetovanie rebríčka: Zadané nesprávne heslo.")
                self.send_error(403, "Forbidden", "Nesprávne Admin Heslo.")

        except Exception as e:
            print(f"Chyba pri spracovaní admin_reset POST: {e}")
            if not self.wfile.closed:
                try:
                    self.send_error(500, "Internal Server Error", "Nepodarilo sa spracovať požiadavku na reset.")
                except Exception as send_err:
                     print(f"Chyba pri odosielaní odpovede 500: {send_err}")

    # --- Pomocné metódy pre odpovede ---
    def send_html_response(self, html_content):
        """Odošle odpoveď 200 OK s HTML obsahom."""
        try:
            encoded_html = html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded_html)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate") # Zabráni cachovaniu
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(encoded_html)
        except Exception as e:
             print(f"Chyba pri odosielaní HTML odpovede: {e}")
             if not getattr(self, 'headers_sent', False) and not self.wfile.closed:
                 try:
                    print("Nebolo možné odoslať chybovú odpoveď, pripojenie môže byť zatvorené.")
                 except Exception as send_err:
                     print(f"Chyba pri odosielaní odpovede 500 po počiatočnom zlyhaní: {send_err}")

    def send_csv_response(self, csv_data, filename):
        """Odošle odpoveď 200 OK s CSV dátami ako prílohou."""
        try:
            encoded_csv = csv_data.encode("utf-8")
            # Zahrnuté UTF-8 BOM pre lepšiu kompatibilitu s Excelom
            bom_plus_csv = b'\xef\xbb\xbf' + encoded_csv

            self.send_response(200)
            self.send_header("Content-type", "text/csv; charset=utf-8")
            # Zabezpečí, že názov súboru je bezpečný pre hlavičku pomocou URL kódovania
            safe_filename = urllib.parse.quote(filename, safe='')
            self.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"')
            self.send_header("Content-Length", str(len(bom_plus_csv)))
            self.end_headers()
            self.wfile.write(bom_plus_csv)
        except Exception as e:
             print(f"Chyba pri odosielaní CSV odpovede pre {filename}: {e}")
             if not getattr(self, 'headers_sent', False) and not self.wfile.closed:
                  try:
                      # self.send_error(500, "Internal Server Error", "Failed to generate CSV file")
                      print("Nebolo možné odoslať chybovú odpoveď, pripojenie môže byť zatvorené.")
                  except Exception as send_err:
                      print(f"Chyba pri odosielaní odpovede 500 po počiatočnom zlyhaní: {send_err}")

    def send_redirect_response(self, location):
        """Odošle odpoveď 303 See Other na presmerovanie."""
        try:
            self.send_response(303) # Použije 303 na presmerovanie po POST
            self.send_header("Location", location)
            self.end_headers()
        except Exception as e:
            print(f"Chyba pri odosielaní presmerovania na {location}: {e}")

def get_server_ip():
    """Pokúsi sa určiť lokálnu IP adresu servera na zobrazenie."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1) 
        s.connect(("8.8.8.8", 80)) 
        local_ip = s.getsockname()[0]
        if not local_ip.startswith("127."): # Ignoruje loop, ak sa nájde IP
            return local_ip
    except Exception:
        pass 
    finally:
        if s: s.close()
    # Metóda 2: Získanie názvu hostiteľa a jeho rozlíšenie (záloha)
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return local_ip
    except Exception as e:
        print(f"Nepodarilo sa určiť IP cez názov hostiteľa: {e}. Používam '127.0.0.1'.")
        return "127.0.0.1" # Posledná možnosť

def show_ip_popup(ip_address, port):
    """Zobrazí malé okno Tkinter s URL servera a otvorí ho."""
    popup_root = tk.Tk()
    popup_root.title("Server beží")
    popup_root.attributes('-topmost', True) # Prinesie okno dopredu
    popup_root.geometry("380x130") 
    popup_root.resizable(False, False)

    message_label = tk.Label(popup_root, text="Web server bol spustený na adrese:", font=("Segoe UI", 10))
    message_label.pack(pady=(10, 5))

    # Použije zistenú IP na zobrazenie, ale server počúva na 0.0.0.0
    display_url = f"http://{ip_address}:{port}"
    local_url = f"http://localhost:{port}"

    # Pole na jednoduché kopírovanie
    url_entry = tk.Entry(popup_root, width=45, font=("Segoe UI", 10, "bold"), bd=0, relief=tk.FLAT, justify='center')
    url_entry.insert(0, display_url)
    url_entry.config(state='readonly', readonlybackground='white', fg='blue') 
    url_entry.pack(pady=2)

    # Popisok pre prístup cez localhost
    local_label = tk.Label(popup_root, text=f"(alebo {local_url})", font=("Segoe UI", 9), fg="#555")
    local_label.pack(pady=(0, 5))

    # Tlačidlo na otvorenie prehliadača
    open_button = ttk.Button(popup_root, text="Otvoriť v prehliadači", command=lambda u=display_url: webbrowser.open(u))
    open_button.pack(pady=5)

    # Vycentruje vyskakovacie okno
    popup_root.update_idletasks()
    width = popup_root.winfo_width()
    height = popup_root.winfo_height()
    screen_width = popup_root.winfo_screenwidth()
    screen_height = popup_root.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    popup_root.geometry(f'{width}x{height}+{x}+{y}')

    # Automaticky otvorí prehliadač po krátkom oneskorení
    popup_root.after(1200, lambda u=display_url: webbrowser.open(u))

    popup_root.mainloop()

def run_web_server(host, port):
    """Spustí HTTP server."""
    server_address = (host, port)
    httpd = None
    try:
        # Umožní rýchle opätovné použitie adresy po vypnutí
        HTTPServer.allow_reuse_address = True
        httpd = HTTPServer(server_address, SimpleRequestHandler)
        display_ip = get_server_ip()
        print(f"--- Web server sa spúšťa na {host}:{port} ---")
        print(f"Prístupové body:")
        print(f"  - Špecifická IP: http://{display_ip}:{port}")
        print(f"  - Localhost:   http://localhost:{port}")
        print(f"  - (Počúva na všetkých rozhraniach, ak je hostiteľ 0.0.0.0)")
        print("Stlačte Ctrl+C na zastavenie servera.")
        httpd.serve_forever()
    except OSError as e:
         if e.errno in [98, 10048, 48]: 
             print(f"\nCHYBA: Port {port} je už používaný.")
             print("Prosím, zatvorte druhú aplikáciu používajúcu tento port,")
             print(f"alebo zmeňte WEB_SERVER_PORT v skripte a reštartujte.")
         else:
             print(f"\nCHYBA: Nepodarilo sa spustiť web server: {e}")
         # Signalizuje ak sa server nepodarí spustiť
         messagebox.showerror("Chyba servera", f"Nepodarilo sa spustiť web server na porte {port}.\nChyba: {e}\n\nProsím, skontrolujte, či port už nie je používaný.")
         os._exit(1) 
    except KeyboardInterrupt:
        print("\nWeb server sa zastavuje (KeyboardInterrupt).")
    except Exception as e:
        print(f"\nVyskytla sa neočakávaná chyba vo web serveri: {e}")
    finally:
        if httpd:
            httpd.server_close()
            print("Web server zatvorený.")

# --- main---
if __name__ == "__main__":
    print("--- Spúšťam aplikáciu rebríčka ---")
    load_leaderboard() 
    load_correct_answers_config()
    root_serial_select = tk.Tk()
    root_serial_select.title("Vyberte sériový port")

    root_serial_select.update_idletasks()
    num_ports = len(list(serial.tools.list_ports.comports()))
    w_select = 400
    h_select = 100 + max(1, num_ports) * 30 # Upraví výšku na základe portov
    sw_select = root_serial_select.winfo_screenwidth()
    sh_select = root_serial_select.winfo_screenheight()
    x_select = (sw_select // 2) - (w_select // 2)
    y_select = (sh_select // 2) - (h_select // 2)
    root_serial_select.geometry(f'{w_select}x{h_select}+{x_select}+{y_select}')
    root_serial_select.attributes('-topmost', True) # Prinesie dopredu

    selected_port = find_serial_port(root_serial_select)

    if selected_port:
        SERIAL_PORT = selected_port
        print(f"Používam sériový port: {SERIAL_PORT}")

        serial_thread = threading.Thread(target=serial_listener, name="SerialListenerThread", daemon=True)
        serial_thread.start()
        print("Vlákno na počúvanie sériového portu spustené.")

        web_server_thread = threading.Thread(target=run_web_server, args=(WEB_SERVER_HOST, WEB_SERVER_PORT), name="WebServerThread", daemon=True)
        web_server_thread.start()
        print("Vlákno web servera sa spúšťa...")

        display_ip_for_popup = get_server_ip()
        popup_thread = threading.Thread(target=show_ip_popup, args=(display_ip_for_popup, WEB_SERVER_PORT), name="PopupThread", daemon=True)
        popup_thread.start()

        print("--- Aplikácia beží ---")
        try:
            while True:
                if not serial_thread.is_alive():
                    print("Chyba: Vlákno na počúvanie sériového portu neočakávane skončilo. Ukončujem.")
                    break 
                if not web_server_thread.is_alive():
                    print("Chyba: Vlákno web servera neočakávane skončilo. Ukončujem.")
                    break 
                time.sleep(1)

        except KeyboardInterrupt:
            print("\nCtrl+C detekované v hlavnom vlákne. Spúšťam vypínanie...")
        finally:
             print("--- Aplikácia sa vypína ---")

    else:
        print("Nebol vybraný žiadny sériový port. Ukončujem aplikáciu.")

   
