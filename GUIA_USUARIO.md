# 📖 Guía Rápida de Uso: Asistente Kindle en Telegram

¡Bienvenido a tu Asistente Personal de Lectura! Con este bot de Telegram podrás buscar cualquier libro y tenerlo listo en tu lector Kindle en menos de un minuto, sin cables ni ordenadores.

---

## 🚀 Paso 1: Configuración Inicial (Solo la primera vez, 1 minuto)

Para que Amazon permita que el bot meta libros en tu dispositivo Kindle, cada lector debe autorizar al bot:

1. Entra a tu cuenta de Amazon en este enlace directo:  
   👉 [Preferencias de Documentos Personales de Amazon](https://www.amazon.es/hz/mycd/myx#/home/settings/payment)
2. Baja hasta el apartado **"Configuración de documentos personales"**.
3. En la sección **"Lista de direcciones de correo electrónico aprobadas para documentos personales"**, pulsa en **"Añadir nueva dirección"** e introduce el correo remitente configurado en tu bot (el valor de `GMAIL_USER` en tu `.env`).
4. Abre Telegram y entra en tu bot.
5. Pulsa el botón **Iniciar** y toca tu dispositivo:
   * `[ 👨‍🦳 Kindle de Papá ]`
   * `[ 👦 Kindle de Gonzalo ]`
   * `[ 👤 Mi Kindle ]`

¡Y listo! Ya no tendrás que volver a configurar nada más.

---

## 🔍 Paso 2: Cómo pedir libros

Tienes dos formas muy sencillas de elegir tu próxima lectura:

### Opción A: Escribe directamente el libro o autor
Simplemente escribe en el chat lo que quieras leer, tal como hablarías con una persona:
* `Dune`
* `El principito`
* `Stephen King`
* `Carmen Mola`

*(Si buscas un libro en otro idioma, puedes poner: `Atomic Habits en inglés`)*.

### Opción B: Toca el botón "Explorar por Temas" 📚
Si no tienes un título pensado y te apetece descubrir libros de un género:
1. Toca el botón **`📚 Explorar por Temas`** en la parte inferior de tu pantalla.
2. Navega entre las 3 páginas con **`[ Siguiente ➡️ ]`** y elige tu temática favorita entre los **24 géneros disponibles**:
   * 🏺 *Arqueología y Civilizaciones Antiguas* (Egipto, Roma, Grecia, grandes descubrimientos)
   * 🦴 *Antropología y Evolución Humana* (orígenes, culturas del mundo)
   * 🏛️ *Arquitectura, Urbanismo y Diseño*
   * ⚔️ *Novela Histórica Épica*
   * 📜 *Historia y Crónicas de España*
   * 🪖 *Ficción Bélica y Militar*
   * 🕵️ *Espionaje y Guerra Fría*
   * 🌐 *Geopolítica y Estrategia*
   * 🔍 *Novela Negra y Policiaca*
   * 🕵️‍♂️ *Mafia, Crimen Organizado y Crónica Real*
   * 🧭 *Grandes Viajes y Exploración* (Polo Sur, expediciones, navegantes)
   * 🤔 *Filosofía y Grandes Pensadores* (Estoicismo, clásicos, ética)
   * 👤 *Biografías y Memorias*
   * 🔬 *Divulgación Científica y Tecnología*
   * 📖 *Grandes Clásicos de la Literatura*
   * ... y muchos más.
3. El bot te mostrará los mejores libros en español de esa categoría.

---

## 🖼️ Paso 3: Previsualización y Envío a tu Kindle

1. En la lista de resultados, toca el libro que más te llame la atención.
2. Se abrirá la **Ficha del Libro con su Portada oficial**:
   * Podrás ver la foto de la portada, el título completo, autor, año, idioma y tamaño del archivo.
3. Si es el que quieres, pulsa el botón:  
   👉 **`[ 🚀 Enviar a mi Kindle ]`**
4. Verás cómo el bot te informa en directo:
   * 📥 *Descargando el libro...*
   * ✉️ *Enviando a tu Kindle...*
   * 📬 *Verificando con Amazon...*
   * 🎉 *¡Listo!*

---

## 📖 Paso 4: Cómo empezar a leer en tu Kindle físico

1. Enciende tu dispositivo Kindle y asegúrate de que el **Wi-Fi esté activado**.
2. Desliza el dedo desde la parte superior de la pantalla hacia abajo y pulsa el icono **"Sincronizar"**.
3. En tu biblioteca aparecerá el libro descargado listo para abrir.

> [!TIP]
> **En Kindles modernos:** Si no ves el libro inmediatamente en la pantalla principal, revisa el filtro de tu biblioteca (arriba a la izquierda) y asegúrate de que esté marcado en **"Documentos"** o **"Todos"** (los libros enviados por correo entran en la sección Documentos).

---

## 🗣️ Palabras útiles (Sin comandos ni barras `/`)

No necesitas escribir comandos raros ni barras `/`. El bot entiende palabras normales si las escribes en el chat:

* **`reiniciar`** o **`inicio`**: Vuelve al saludo y menú principal.
* **`temas`** o **`géneros`**: Abre el explorador de temáticas.
* **`kindle`**: Te permite cambiar de lector en cualquier momento.
* **`ayuda`**: Vuelve a mostrarte estas instrucciones.
