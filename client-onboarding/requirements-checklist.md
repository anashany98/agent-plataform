# Lista de Requisitos Previos para la Instalación del Cliente Piloto

**Cliente:** [Nombre de la Empresa]  
**Fecha de Revisión:** [Fecha]  

---

## 1. Requisitos Técnicos e Infraestructura
- [ ] Servidor host con Docker Engine 24+ y Docker Compose v2+ instalado.
- [ ] Mínimo 4 vCPUs, 8 GB RAM y 30 GB almacenamiento SSD.
- [ ] Dominio o subdominio DNS apuntando a la IP del servidor.
- [ ] Puertos 80/443 abiertos en el cortafuegos.
- [ ] Certificado TLS/SSL configurado o Let's Encrypt habilitado.

## 2. Requisitos de Datos Comerciales
- [ ] Fichero `products-import-template.csv` cumplimentado (mínimo 10 productos).
- [ ] Fichero `customers-import-template.csv` cumplimentado (mínimo 5 clientes).
- [ ] Fichero `stock-import-template.csv` con niveles iniciales de inventario.
- [ ] Documentación técnica y FAQs en formato PDF/TXT/MD para la Base de Conocimiento RAG.

## 3. Requisitos Organizativos y Personal
- [ ] Designación de un Responsable del Piloto por parte del cliente.
- [ ] Lista de usuarios administradores y operadores (`users-template.csv`).
- [ ] Aceptación del documento de alcance del piloto (`pilot-scope.md`).
