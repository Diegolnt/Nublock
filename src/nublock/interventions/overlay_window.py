"""Ventana del overlay (proceso aparte). Uso: python -m nublock.interventions.overlay_window MSG"""

import sys
import tkinter as tk


def main(message: str) -> None:
    root = tk.Tk()  # la ventana principal de tkinter
    width, height = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{width}x{height}+0+0")  # "ANCHOxALTO+X+Y": cubre la pantalla principal
    root.overrideredirect(True)  # sin barra de título ni bordes
    root.attributes("-topmost", True)  # siempre encima de las otras ventanas
    root.attributes("-alpha", 0.88)  # semitransparente
    root.configure(background="#1d2b3a")
    frame = tk.Frame(root, background="#1d2b3a")
    frame.place(relx=0.5, rely=0.5, anchor="center")
    tk.Label(
        frame,
        text=message,
        font=("Helvetica", 34, "bold"),
        fg="white",
        bg="#1d2b3a",
        wraplength=900,
    ).pack(pady=24)
    tk.Button(frame, text="Volver al trabajo", font=("Helvetica", 18), command=root.destroy).pack()
    root.bind("<Escape>", lambda _event: root.destroy())
    root.mainloop()  # bloquea hasta que la ventana se cierra


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Vuelve a tu sesión de foco")
