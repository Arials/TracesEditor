¡Fantástico! Me alegra mucho saber que ha funcionado para la navegación dentro de la misma pestaña. Ese era el caso de uso principal que queríamos resolver.

Entiendo lo de las pestañas distintas; la gestión del "activeSessionId" entre pestañas es un desafío aparte (generalmente se usaría `localStorage` también para sincronizar el ID de la sesión activa, pero eso está fuera del alcance de este problema inmediato).


Errores:
* Al seleccionar una trace, ya sea de transformación o original en MacPage - "Failed to load rules: Not Found"