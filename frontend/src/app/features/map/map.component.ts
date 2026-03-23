import { Component, OnInit, OnDestroy, ChangeDetectionStrategy } from '@angular/core';
import * as L from 'leaflet';

@Component({
  selector: 'whm-map',
  standalone: true,
  templateUrl: './map.component.html',
  styleUrl: './map.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MapComponent implements OnInit, OnDestroy {
  private map: L.Map | null = null;

  private static readonly ODESA_CENTER: L.LatLngTuple = [46.4825, 30.7233];
  private static readonly DEFAULT_ZOOM = 13;

  public ngOnInit(): void {
    MapComponent.fixLeafletIcons();
    this.map = L.map('map').setView(MapComponent.ODESA_CENTER, MapComponent.DEFAULT_ZOOM);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(this.map);
  }

  public ngOnDestroy(): void {
    this.map?.remove();
  }

  private static fixLeafletIcons(): void {
    const iconDefault = L.icon({
      iconRetinaUrl: 'marker-icon-2x.png',
      iconUrl: 'marker-icon.png',
      shadowUrl: 'marker-shadow.png',
      iconSize: [25, 41],
      iconAnchor: [12, 41],
      popupAnchor: [1, -34],
      tooltipAnchor: [16, -28],
      shadowSize: [41, 41],
    });
    L.Marker.prototype.options.icon = iconDefault;
  }
}
