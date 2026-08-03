/**
 * Etiquetas del portal (español). Recortado a los módulos reales de la
 * candidata core (Ruta A): cualquier módulo fuera de este mapa no debe
 * aparecer en la navegación para no prometer funcionalidad fantasma.
 */
export const translations = {
  appName: 'Plataforma de Agentes IA',
  pilotModeBanner:
    'Modo piloto activo: las acciones sensibles requieren aprobación humana.',
  nav: {
    resumen: 'Resumen',
    aprobaciones: 'Aprobaciones',
    catalogo: 'Productos',
    documentos: 'Documentos',
    agentes: 'Agentes de IA',
    automatizaciones: 'Automatizaciones',
    usuarios: 'Usuarios y permisos',
  },
  status: {
    configured: 'Configurado',
    pending: 'Pendiente de configuración',
    loading: 'Cargando…',
  },
};

export type Translations = typeof translations;
