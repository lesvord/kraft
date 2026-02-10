import sys
import tkinter as tk
from tkinter import ttk, messagebox
import threading

from license_client import LicenseClient
from bot_gui import CraftBotGUI

SERVER_URL = "http://95.164.23.186:5000"


class LicenseWindow:
    """Простое окно ввода/активации лицензии (лоадер + блок кнопки)."""

    def __init__(self, client: LicenseClient, initial_key: str = ""):
        self.client = client
        self.activated = False

        self.root = tk.Tk()
        self.root.title("Активация лицензии")
        self.root.geometry("500x260")
        self.root.resizable(False, False)

        ttk.Label(self.root, text="Введите новую лицензию (UUID)", font=("Arial", 11, "bold")).pack(pady=10)

        self.key_var = tk.StringVar(value=(initial_key or ""))
        self.entry = ttk.Entry(self.root, textvariable=self.key_var, width=58)
        self.entry.pack(pady=5)
        self.entry.focus()

        self.status_lbl = ttk.Label(self.root, text="", foreground="blue")
        self.status_lbl.pack(pady=5)

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=20, pady=5)

        btns = ttk.Frame(self.root)
        btns.pack(pady=10)

        self.activate_btn = ttk.Button(btns, text="АКТИВИРОВАТЬ", command=self.activate)
        self.activate_btn.grid(row=0, column=0, padx=6)

        self.reset_btn = ttk.Button(btns, text="СБРОСИТЬ ЛИЦЕНЗИЮ", command=self.reset_local_license)
        self.reset_btn.grid(row=0, column=1, padx=6)

        self.exit_btn = ttk.Button(btns, text="ВЫХОД", command=self.root.destroy)
        self.exit_btn.grid(row=0, column=2, padx=6)

        ttk.Label(self.root, text=f"HWID: {self.client.hardware_id}", font=("Courier", 8)).pack(pady=5)

        self.root.bind("<Return>", lambda e: self.activate())
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def reset_local_license(self):
        """Локально сбрасывает лицензию (файл), HWID сохраняется."""
        if messagebox.askyesno("Сброс", "Удалить локальные данные лицензии?\n(На сервере ключ не изменится)"):
            try:
                self.client.reset_license()
                self.key_var.set("")
                self.status_lbl.config(text="Локальная лицензия сброшена. Введите новый ключ.", foreground="blue")
            except Exception as e:
                self.status_lbl.config(text=f"Ошибка сброса: {e}", foreground="red")

    def activate(self):
        key = self.key_var.get().strip().lower()

        if not key:
            self.status_lbl.config(text="Введите ключ", foreground="red")
            return

        self.activate_btn.config(state=tk.DISABLED)
        self.reset_btn.config(state=tk.DISABLED)
        self.progress.start(10)
        self.status_lbl.config(text="Активация...", foreground="blue")

        def worker():
            try:
                result = self.client.register_license(key)
            except Exception as e:
                result = {"valid": False, "message": str(e)}
            self.root.after(0, lambda: self.finish(result))

        threading.Thread(target=worker, daemon=True).start()

    def finish(self, result: dict):
        self.progress.stop()
        self.activate_btn.config(state=tk.NORMAL)
        self.reset_btn.config(state=tk.NORMAL)

        if result.get("valid"):
            self.activated = True
            messagebox.showinfo("Успех", "Лицензия активирована.\nОкно будет закрыто.")
            self.root.destroy()
        else:
            self.status_lbl.config(text=result.get("message", "Ошибка активации"), foreground="red")

    def run(self) -> bool:
        self.root.mainloop()
        return self.activated


def validate_online(client: LicenseClient) -> bool:
    """
    Проверка на сервере.
    Возвращает True если valid, иначе False.
    """
    try:
        res = client.validate_license()
        return bool(res.get("valid"))
    except:
        return False


def run_app_with_minute_license_check(client: LicenseClient):
    """
    Запускает основное приложение и включает проверку лицензии каждую минуту.
    Если лицензия становится недействительной — закрывает приложение.
    """
    app = CraftBotGUI(client)

    def on_license_invalid(reason: str):
        # callback приходит из фонового потока -> показываем всё через after()
        def kill():
            try:
                messagebox.showerror(
                    "Лицензия отключена",
                    "Лицензия стала недействительной.\n\n"
                    f"Причина: {reason}\n\n"
                    "Приложение будет закрыто."
                )
            except:
                pass

            try:
                if hasattr(app, "root") and app.root.winfo_exists():
                    app.root.destroy()
            except:
                pass

            sys.exit(0)

        try:
            if hasattr(app, "root") and app.root.winfo_exists():
                app.root.after(0, kill)
            else:
                kill()
        except:
            kill()

    client.set_license_invalid_callback(on_license_invalid)

    # У тебя в license_client.py interval уже 60 секунд
    client.start_background_check()

    try:
        app.run()
    finally:
        try:
            client.stop_background_check()
        except:
            pass


def ensure_active_license_or_prompt(client: LicenseClient) -> bool:
    """
    Гарантирует активную лицензию:
    - пытается загрузить локальные данные
    - проверяет локально (по сроку)
    - проверяет онлайн (сервер)
    Если не активна -> просит ввести новую лицензию (окно активации).
    Возвращает True если лицензия активна и можно запускать приложение.
    """
    # 1) грузим локальные данные (если есть)
    client.load_license_data()

    # 2) проверяем локально
    local_ok = client.is_license_active()

    # 3) если локально ок, дополнительно проверим на сервере (на старте)
    online_ok = False
    if local_ok and client.license_key:
        online_ok = validate_online(client)

    if local_ok and online_ok:
        return True

    # Если локально НЕ ок или сервер сказал НЕ ок -> просим новую лицензию
    # (подставим текущий ключ если есть, чтобы было видно что было)
    initial_key = client.license_key or ""

    # Можно сразу сбросить локальную как “честный старт”
    # но лучше дать кнопку "СБРОСИТЬ" в окне (она уже есть)
    win = LicenseWindow(client, initial_key=initial_key)
    return win.run()


def main():
    client = LicenseClient(SERVER_URL)

    # Требование: при запуске если лицензия не активна -> просим новую
    ok = ensure_active_license_or_prompt(client)
    if not ok:
        sys.exit(0)

    # После успешной активации/проверки -> запускаем приложение + минутную проверку
    run_app_with_minute_license_check(client)


if __name__ == "__main__":
    main()
