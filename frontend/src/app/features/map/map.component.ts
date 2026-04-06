import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  OnDestroy,
  OnInit,
  signal,
  viewChild,
} from '@angular/core';
import { GoogleMap, GoogleMapsModule } from '@angular/google-maps';
import { MarkerClusterer } from '@googlemaps/markerclusterer';
import { FilterPanelComponent } from './components/filter-panel/filter-panel.component';
import { StatsComponent } from './components/stats/stats.component';
import { RouteCheckComponent } from './components/route-check/route-check.component';
import { MapDataService } from './services/map-data.service';
import { FilterService } from './services/filter.service';
import { GoogleMapsLoaderService } from '../../core/services/google-maps-loader.service';
import { MapApiService, RouteCheckResponse } from '../../core/services/map-api.service';
import type { DisplayMode } from './services/filter.service';
import type { BBox } from './services/map-data.service';
import { LocationFeature } from '../../core/services/map-api.service';

const HEATMAP_ZOOM_THRESHOLD = 14;
const ODESA_CENTER = { lat: 46.4825, lng: 30.7233 };
const DEFAULT_ZOOM = 13;
const ODESA_CITY_ID = 1;

// Swiss Minimal map style: desaturated, no commercial POI
const MAP_STYLES: google.maps.MapTypeStyle[] = [
  { elementType: 'geometry', stylers: [{ color: '#f5f5f5' }] },
  { elementType: 'labels.icon', stylers: [{ visibility: 'off' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#616161' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#f5f5f5' }] },
  { featureType: 'administrative.land_parcel', elementType: 'labels.text.fill', stylers: [{ color: '#bdbdbd' }] },
  { featureType: 'poi', elementType: 'geometry', stylers: [{ color: '#eeeeee' }] },
  { featureType: 'poi', elementType: 'labels.text.fill', stylers: [{ color: '#757575' }] },
  { featureType: 'poi.park', elementType: 'geometry', stylers: [{ color: '#e5e5e5' }] },
  { featureType: 'poi.park', elementType: 'labels.text.fill', stylers: [{ color: '#9e9e9e' }] },
  { featureType: 'poi.business', stylers: [{ visibility: 'off' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#ffffff' }] },
  { featureType: 'road.arterial', elementType: 'labels.text.fill', stylers: [{ color: '#757575' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#dadada' }] },
  { featureType: 'road.highway', elementType: 'labels.text.fill', stylers: [{ color: '#616161' }] },
  { featureType: 'road.local', elementType: 'labels.text.fill', stylers: [{ color: '#9e9e9e' }] },
  { featureType: 'transit.line', elementType: 'geometry', stylers: [{ color: '#e5e5e5' }] },
  { featureType: 'transit.station', elementType: 'geometry', stylers: [{ color: '#eeeeee' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#c9c9c9' }] },
  { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#9e9e9e' }] },
];

@Component({
  selector: 'whm-map',
  standalone: true,
  templateUrl: './map.component.html',
  styleUrl: './map.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [MapDataService],
  imports: [GoogleMapsModule, FilterPanelComponent, StatsComponent, RouteCheckComponent],
})
export class MapComponent implements OnInit, OnDestroy {
  private readonly mapData = inject(MapDataService);
  private readonly filterService = inject(FilterService);
  private readonly mapsLoader = inject(GoogleMapsLoaderService);
  private readonly api = inject(MapApiService);

  readonly mapRef = viewChild<GoogleMap>('googleMap');
  readonly mapReady = signal(false);

  readonly mapOptions: google.maps.MapOptions = {
    center: ODESA_CENTER,
    zoom: DEFAULT_ZOOM,
    styles: MAP_STYLES,
    disableDefaultUI: false,
    zoomControl: true,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: false,
  };

  readonly currentZoom = signal(DEFAULT_ZOOM);

  private markerCluster: MarkerClusterer | null = null;
  private markers: google.maps.Marker[] = [];
  private heatLayer: google.maps.visualization.HeatmapLayer | null = null;
  private districtData: google.maps.Data | null = null;
  private routePolyline: google.maps.Polyline | null = null;
  private routeCircles: google.maps.Circle[] = [];
  private infoWindow: google.maps.InfoWindow | null = null;

  constructor() {
    effect(() => {
      if (this.mapReady()) {
        this.updateMarkerCluster(this.mapData.locations().features);
      }
    });

    effect(() => {
      if (this.mapReady()) {
        this.updateHeatLayer(this.mapData.heatmapPoints());
      }
    });

    effect(() => {
      if (this.mapReady()) {
        this.updateLayerVisibility(this.filterService.displayMode(), this.currentZoom());
      }
    });
  }

  async ngOnInit(): Promise<void> {
    await this.mapsLoader.load();
    this.infoWindow = new google.maps.InfoWindow();
    this.mapReady.set(true);
    this.loadDistricts();
  }

  ngOnDestroy(): void {
    this.clearRouteLayer();
    this.heatLayer?.setMap(null);
    this.markerCluster?.clearMarkers();
    this.districtData?.setMap(null);
    this.infoWindow?.close();
  }

  onBoundsChanged(): void {
    const map = this.mapRef()?.googleMap;
    if (!map) return;
    const bounds = map.getBounds();
    if (!bounds) return;
    const bbox: BBox = {
      north: bounds.getNorthEast().lat(),
      south: bounds.getSouthWest().lat(),
      east: bounds.getNorthEast().lng(),
      west: bounds.getSouthWest().lng(),
    };
    this.mapData.bboxChanged$.next(bbox);
  }

  onZoomChanged(): void {
    const zoom = this.mapRef()?.googleMap?.getZoom();
    if (zoom !== undefined) {
      this.currentZoom.set(zoom);
    }
  }

  onRouteResult(result: RouteCheckResponse | null): void {
    this.clearRouteLayer();
    if (!result) return;

    const map = this.mapRef()?.googleMap;
    if (!map) return;

    const latlngs = result.route.coordinates.map(([lng, lat]) => ({ lat, lng }));
    this.routePolyline = new google.maps.Polyline({
      path: latlngs,
      strokeColor: '#1a73e8',
      strokeWeight: 4,
      strokeOpacity: 0.85,
      icons: [
        {
          icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 4 },
          offset: '0',
          repeat: '20px',
        },
      ],
      map,
    });

    this.routeCircles = result.danger_locations.map((loc) => {
      const circle = new google.maps.Circle({
        center: { lat: loc.lat, lng: loc.lng },
        radius: 30,
        strokeColor: '#c0392b',
        strokeWeight: 2,
        fillColor: '#c0392b',
        fillOpacity: 0.8,
        map,
      });

      circle.addListener('click', () => {
        if (!this.infoWindow) {
          this.infoWindow = new google.maps.InfoWindow();
        }
        this.infoWindow.setContent(
          `<b>${loc.address}</b><br>
           <span class="confidence">${Math.round(loc.confidence * 100)}%</span><br>
           <small>${loc.post_date ?? ''}</small>`,
        );
        this.infoWindow.setPosition({ lat: loc.lat, lng: loc.lng });
        this.infoWindow.open(map);
      });

      return circle;
    });
  }

  private loadDistricts(): void {
    const map = this.mapRef()?.googleMap;
    if (!map) return;

    this.districtData = new google.maps.Data();

    this.api.getDistricts(ODESA_CITY_ID).subscribe({
      next: (data) => {
        this.districtData!.addGeoJson(data as unknown as object);
        this.districtData!.setStyle({
          strokeColor: '#111',
          strokeWeight: 1,
          fillColor: '#c0392b',
          fillOpacity: 0.06,
        });
        this.districtData!.addListener('mouseover', (event: google.maps.Data.MouseEvent) => {
          const name = event.feature.getProperty('name') as string | undefined;
          if (name && this.infoWindow) {
            this.infoWindow.setContent(name);
            this.infoWindow.setPosition(event.latLng ?? undefined);
            this.infoWindow.open(map);
          }
        });
        if (this.filterService.displayMode() === 'districts') {
          this.districtData!.setMap(map);
        }
      },
      error: () => {
        // districts are optional — fail silently
      },
    });
  }

  private updateMarkerCluster(features: LocationFeature[]): void {
    const map = this.mapRef()?.googleMap;
    if (!map) return;

    // clear old markers
    this.markers.forEach((m) => m.setMap(null));
    this.markers = [];
    if (!this.infoWindow) {
      this.infoWindow = new google.maps.InfoWindow();
    }

    this.markers = features
      .filter((f) => f.geometry.type === 'Point')
      .map((feature) => {
        const [lng, lat] = feature.geometry.coordinates;
        const p = feature.properties;
        const confidencePct = Math.round(p.confidence * 100);

        const marker = new google.maps.Marker({
          position: { lat, lng },
          map: null, // added via clusterer
        });

        marker.addListener('click', () => {
          this.infoWindow!.setContent(
            `<b>${p.address}</b><br>
             <span class="geo-badge">${p.geo_type}</span>
             <span class="confidence">${confidencePct}%</span><br>
             <small>${p.post_date ?? ''}</small>
             ${p.post_excerpt ? `<p class="excerpt">${p.post_excerpt}</p>` : ''}`,
          );
          this.infoWindow!.open(map, marker);
        });

        return marker;
      });

    if (!this.markerCluster) {
      this.markerCluster = new MarkerClusterer({ map, markers: [] });
    }
    this.markerCluster.clearMarkers();
    this.markerCluster.addMarkers(this.markers);
  }

  private updateHeatLayer(points: [number, number, number][]): void {
    const map = this.mapRef()?.googleMap;
    if (!map) return;

    if (this.heatLayer) {
      this.heatLayer.setMap(null);
      this.heatLayer = null;
    }

    if (points.length === 0) return;

    const weightedPoints = points.map(([lat, lng, weight]) => ({
      location: new google.maps.LatLng(lat, lng),
      weight,
    }));

    this.heatLayer = new google.maps.visualization.HeatmapLayer({
      data: weightedPoints,
      radius: 25,
      opacity: 0.7,
    });

    const mode = this.filterService.displayMode();
    const zoom = this.currentZoom();

    if (mode === 'heatmap' || (mode === 'points' && zoom < HEATMAP_ZOOM_THRESHOLD)) {
      this.heatLayer.setMap(map);
    }
  }

  private updateLayerVisibility(mode: DisplayMode, zoom: number): void {
    const map = this.mapRef()?.googleMap;
    if (!map) return;

    switch (mode) {
      case 'heatmap':
        this.heatLayer?.setMap(map);
        this.setMarkersMap(null);
        this.districtData?.setMap(null);
        break;

      case 'points':
        if (zoom >= HEATMAP_ZOOM_THRESHOLD) {
          this.heatLayer?.setMap(null);
          this.setMarkersMap(map);
        } else {
          this.heatLayer?.setMap(map);
          this.setMarkersMap(null);
        }
        this.districtData?.setMap(null);
        break;

      case 'districts':
        this.heatLayer?.setMap(null);
        this.setMarkersMap(null);
        this.districtData?.setMap(map);
        break;
    }
  }

  private setMarkersMap(map: google.maps.Map | null): void {
    if (map) {
      // Show: re-add markers to clusterer (clusterer manages map assignment)
      this.markerCluster?.clearMarkers();
      this.markerCluster?.addMarkers(this.markers);
    } else {
      // Hide: remove all markers from map and clear clusterer
      this.markers.forEach((m) => m.setMap(null));
      this.markerCluster?.clearMarkers();
    }
  }

  private clearRouteLayer(): void {
    this.routePolyline?.setMap(null);
    this.routePolyline = null;
    this.routeCircles.forEach((c) => c.setMap(null));
    this.routeCircles = [];
  }
}
