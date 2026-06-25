"""
colores.py
==========

Script simple con tres funciones de impresión coloreada usando colorama:
    - imprimir_verde()    -> verde claro
    - imprimir_amarillo() -> amarillo
    - imprimir_rojo()     -> rojo oscuro

Uso:
    from colores import imprimir_verde, imprimir_amarillo, imprimir_rojo

    imprimir_verde("Todo correcto")
    imprimir_amarillo("Aviso")
    imprimir_rojo("Error")
"""

from colorama import Fore, Style, init

# autoreset=True restaura el color por defecto tras cada print automáticamente.
init(autoreset=True)


def imprimir_verde(texto: str) -> None:
    """Imprime el texto en verde claro."""
    print(Fore.LIGHTGREEN_EX + texto + Style.RESET_ALL)


def imprimir_amarillo(texto: str) -> None:
    """Imprime el texto en amarillo."""
    print(Fore.YELLOW + texto + Style.RESET_ALL)


def imprimir_rojo(texto: str) -> None:
    """Imprime el texto en rojo oscuro."""
    print(Fore.RED + texto + Style.RESET_ALL)


if __name__ == "__main__":
    imprimir_verde("Verde claro: operación exitosa")
    imprimir_amarillo("Amarillo: advertencia")
    imprimir_rojo("Rojo oscuro: error")
