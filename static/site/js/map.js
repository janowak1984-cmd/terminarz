// standardowa ikona Leaflet ustawiona ręcznie
var defaultIcon = L.icon({
    iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41]
});

// mapa ustawiona na Łódź
var map = L.map('map').setView([51.76378216670105, 19.46087448036354], 18);

// warstwa OSM
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
}).addTo(map);

// marker na Łódź
var marker = L.marker([51.76378216670105, 19.46087448036354], { icon: defaultIcon }).addTo(map);
marker.bindPopup("Gabinet Sienkiewicza 59/31").openPopup();