"use client";

import { Fragment, useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { MANDIS, REFERENCE_VILLAGE } from "@/lib/mock/mandis";
import { rupees } from "@/lib/format";

/** Fits the view to every mandi plus the village, so the map never opens blank. */
function FitBounds() {
  const map = useMap();
  useEffect(() => {
    const points: [number, number][] = [
      [REFERENCE_VILLAGE.lat, REFERENCE_VILLAGE.lon],
      ...MANDIS.map((m) => [m.lat, m.lon] as [number, number]),
    ];
    map.fitBounds(points, { padding: [40, 40] });
  }, [map]);
  return null;
}

export default function MandiMap({ height = 420 }: { height?: number }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line" style={{ height }}>
      <MapContainer center={[20.11, 74.2]} zoom={9} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds />

        {MANDIS.map((m) => (
          <Fragment key={m.id}>
            <Polyline
              positions={[
                [REFERENCE_VILLAGE.lat, REFERENCE_VILLAGE.lon],
                [m.lat, m.lon],
              ]}
              pathOptions={{ color: "#16160F", weight: 1, opacity: 0.2, dashArray: "4 5" }}
            />
            <CircleMarker
              center={[m.lat, m.lon]}
              radius={9}
              pathOptions={{ color: "#16160F", fillColor: "#16160F", fillOpacity: 0.85, weight: 2 }}
            >
              <Popup>
                <p className="text-[0.9rem] font-semibold">{m.name}</p>
                <p className="text-[0.8rem]">
                  {rupees(m.todayModal)}/qtl · {m.distanceKm} km
                </p>
                <p className="text-[0.75rem] opacity-70">
                  Arrivals {m.arrivalQtl.toLocaleString("en-IN")} qtl
                </p>
              </Popup>
            </CircleMarker>
          </Fragment>
        ))}

        <CircleMarker
          center={[REFERENCE_VILLAGE.lat, REFERENCE_VILLAGE.lon]}
          radius={7}
          pathOptions={{ color: "#1F3D2B", fillColor: "#FFFFFF", fillOpacity: 1, weight: 3 }}
        >
          <Popup>
            <p className="text-[0.9rem] font-semibold">{REFERENCE_VILLAGE.name}</p>
            <p className="text-[0.8rem]">Your village</p>
          </Popup>
        </CircleMarker>
      </MapContainer>
    </div>
  );
}
