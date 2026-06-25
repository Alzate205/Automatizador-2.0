"""
alertas_consola.py
==================

Módulo corto e independiente con tres alertas coloreadas para la consola,
usando colorama. Cada función es de una sola línea.

Uso:
    from alertas_consola import exito, advertencia, error

    exito("Operación completada")
    advertencia("Revisa la configuración")
    error("Algo falló")
"""

from colorama import Fore, Style, init

init(autoreset=True)


def exito(texto: str) -> None:
    print(f"{Fore.GREEN}{Style.BRIGHT}[ÉXITO] {texto}{Style.RESET_ALL}")


def advertencia(texto: str) -> None:
    print(f"{Fore.YELLOW}{Style.BRIGHT}[INFO] {texto}{Style.RESET_ALL}")


def error(texto: str) -> None:
    print(f"{Fore.RED}{Style.BRIGHT}[ERROR] {texto}{Style.RESET_ALL}")


if __name__ == "__main__":
    exito("Operación completada correctamente")
    advertencia("Esto es un mensaje informativo")
    error("Ha ocurrido un problema")
