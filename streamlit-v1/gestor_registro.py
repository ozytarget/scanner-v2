#!/usr/bin/env python3
"""
Herramienta para llevar registro de distribución de passwords
Guarda en CSV y Excel
"""

import csv
import sys
from datetime import datetime

def cargar_registro():
    """Carga el registro actual de alumnos"""
    try:
        with open('registro_alumnos.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except:
        return []

def guardar_registro(alumnos):
    """Guarda el registro de alumnos"""
    if not alumnos:
        return
    
    with open('registro_alumnos.csv', 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['Nombre Alumno', 'Password Asignado', 'Email', 'Fecha Asignación', 'Estado']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(alumnos)

def mostrar_menu():
    """Muestra el menú principal"""
    print("\n" + "="*70)
    print("📋 REGISTRO DE DISTRIBUCIÓN DE PASSWORDS")
    print("="*70)
    print("\n1. Asignar password a un alumno")
    print("2. Ver registro actual")
    print("3. Ver passwords disponibles")
    print("4. Buscar alumno")
    print("5. Salir")
    print("\n" + "-"*70)

def obtener_passwords_usados(alumnos):
    """Obtiene los passwords ya asignados"""
    return [a.get('Password Asignado', '').strip() for a in alumnos if a.get('Password Asignado', '').strip()]

def obtener_todos_passwords():
    """Lee los 40 passwords del archivo"""
    try:
        with open('40_passwords.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        passwords = []
        for line in lines:
            line = line.strip()
            if line and '.' in line and len(line) > 3:
                pwd = line.split('. ', 1)[1]
                passwords.append(pwd)
        return passwords
    except:
        return []

def asignar_password():
    """Asigna un password a un alumno"""
    alumnos = cargar_registro()
    
    # Obtener passwords disponibles
    todos_passwords = obtener_todos_passwords()
    usados = obtener_passwords_usados(alumnos)
    disponibles = [p for p in todos_passwords if p not in usados]
    
    print("\n" + "-"*70)
    print(f"📊 Passwords disponibles: {len(disponibles)}/{len(todos_passwords)}")
    print("-"*70)
    
    nombre = input("\n👤 Nombre del alumno: ").strip()
    if not nombre:
        print("❌ Nombre requerido")
        return
    
    # Mostrar passwords disponibles
    print("\n🔑 Passwords disponibles:")
    for i, pwd in enumerate(disponibles[:10], 1):
        print(f"   {i}. {pwd}")
    if len(disponibles) > 10:
        print(f"   ... y {len(disponibles) - 10} más")
    
    password = input("\n🔐 Password a asignar: ").strip().lower()
    
    if password not in disponibles:
        print(f"❌ Password no disponible o ya asignado")
        return
    
    email = input("📧 Email (opcional): ").strip()
    
    # Agregar o actualizar
    alumno_existente = False
    for alumno in alumnos:
        if alumno['Nombre Alumno'] == nombre:
            alumno['Password Asignado'] = password
            alumno['Email'] = email
            alumno['Fecha Asignación'] = datetime.now().strftime("%d/%m/%Y %H:%M")
            alumno['Estado'] = 'Asignado'
            alumno_existente = True
            break
    
    if not alumno_existente:
        alumnos.append({
            'Nombre Alumno': nombre,
            'Password Asignado': password,
            'Email': email,
            'Fecha Asignación': datetime.now().strftime("%d/%m/%Y %H:%M"),
            'Estado': 'Asignado'
        })
    
    guardar_registro(alumnos)
    print(f"\n✅ Asignado a {nombre}: {password}")

def ver_registro():
    """Muestra el registro actual"""
    alumnos = cargar_registro()
    
    if not alumnos or all(not a['Nombre Alumno'] for a in alumnos):
        print("\n❌ No hay registros aún")
        return
    
    print("\n" + "="*70)
    print("📋 REGISTRO ACTUAL")
    print("="*70)
    print(f"\n{'Alumno':<20} {'Password':<10} {'Email':<20} {'Fecha':<16}")
    print("-"*70)
    
    for alumno in alumnos:
        if alumno['Nombre Alumno']:
            nombre = alumno['Nombre Alumno'][:19]
            pwd = alumno.get('Password Asignado', '')[:9]
            email = alumno.get('Email', '')[:19]
            fecha = alumno.get('Fecha Asignación', '')[:15]
            print(f"{nombre:<20} {pwd:<10} {email:<20} {fecha:<16}")
    
    # Estadísticas
    asignados = sum(1 for a in alumnos if a.get('Password Asignado', '').strip())
    print("-"*70)
    print(f"✅ Asignados: {asignados} | ⏳ Pendientes: {40 - asignados}")

def ver_disponibles():
    """Muestra los passwords disponibles"""
    todos = obtener_todos_passwords()
    alumnos = cargar_registro()
    usados = obtener_passwords_usados(alumnos)
    disponibles = [p for p in todos if p not in usados]
    
    print("\n" + "="*70)
    print("🔓 PASSWORDS DISPONIBLES")
    print("="*70)
    
    print(f"\n📊 Total disponibles: {len(disponibles)}/{len(todos)}")
    print("\n" + "-"*70)
    
    for i, pwd in enumerate(disponibles, 1):
        print(f"{i:2d}. {pwd}", end="  ")
        if i % 5 == 0:
            print()
    print()

def buscar_alumno():
    """Busca un alumno en el registro"""
    alumnos = cargar_registro()
    nombre = input("\n🔍 Buscar alumno: ").strip().lower()
    
    resultados = [a for a in alumnos if nombre in a.get('Nombre Alumno', '').lower()]
    
    if not resultados:
        print(f"❌ No se encontró '{nombre}'")
        return
    
    print("\n" + "="*70)
    print(f"📋 RESULTADOS ({len(resultados)} encontrado/s)")
    print("="*70)
    
    for alumno in resultados:
        if alumno['Nombre Alumno']:
            print(f"\n👤 Alumno: {alumno['Nombre Alumno']}")
            print(f"🔐 Password: {alumno.get('Password Asignado', 'No asignado')}")
            print(f"📧 Email: {alumno.get('Email', 'No especificado')}")
            print(f"📅 Fecha: {alumno.get('Fecha Asignación', 'N/A')}")
            print(f"✓ Estado: {alumno.get('Estado', 'Pendiente')}")

def main():
    """Programa principal"""
    while True:
        mostrar_menu()
        opcion = input("Selecciona una opción (1-5): ").strip()
        
        if opcion == "1":
            asignar_password()
        elif opcion == "2":
            ver_registro()
        elif opcion == "3":
            ver_disponibles()
        elif opcion == "4":
            buscar_alumno()
        elif opcion == "5":
            print("\n👋 ¡Hasta luego!")
            break
        else:
            print("\n❌ Opción inválida")

if __name__ == "__main__":
    main()
