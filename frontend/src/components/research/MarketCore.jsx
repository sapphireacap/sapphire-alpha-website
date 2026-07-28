import { useEffect, useRef } from "react";
import * as THREE from "three";

// "The Geode" -- a rotating sphere of points whose color and spin speed
// encode overall market breadth, mounted on Aurora. Simplified from the
// original spec's custom vertex/fragment shaders (radial-glow fragment
// shader, size-attenuation vertex shader) to THREE's built-in
// PointsMaterial (sizeAttenuation: true already does most of that) --
// same visual idea, far less GLSL to maintain for a decorative element.
const POINT_COUNT = 800;
const NEIGHBOR_K = 3;
const BASE_ANGULAR_VELOCITY = 0.0015;

function fibonacciSpherePoints(count, radius) {
  const points = [];
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const theta = goldenAngle * i;
    points.push(new THREE.Vector3(Math.cos(theta) * r * radius, y * radius, Math.sin(theta) * r * radius));
  }
  return points;
}

function nearestNeighborSegments(points, k) {
  const positions = [];
  for (let i = 0; i < points.length; i++) {
    const distances = points
      .map((p, j) => (j === i ? null : { j, d: points[i].distanceToSquared(p) }))
      .filter(Boolean)
      .sort((a, b) => a.d - b.d)
      .slice(0, k);
    for (const { j } of distances) {
      positions.push(points[i].x, points[i].y, points[i].z, points[j].x, points[j].y, points[j].z);
    }
  }
  return new Float32Array(positions);
}

export default function MarketCore({ breadthPct = 50, className = "" }) {
  const containerRef = useRef(null);
  const breadthRef = useRef(breadthPct);
  breadthRef.current = breadthPct;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const width = container.clientWidth || 400;
    const height = container.clientHeight || 400;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
    camera.position.z = 3.2;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    const group = new THREE.Group();
    scene.add(group);

    const points = fibonacciSpherePoints(POINT_COUNT, 1.4);
    const pointsGeometry = new THREE.BufferGeometry().setFromPoints(points);
    const pointsMaterial = new THREE.PointsMaterial({ size: 0.035, sizeAttenuation: true, transparent: true, opacity: 0.9 });
    const pointCloud = new THREE.Points(pointsGeometry, pointsMaterial);
    group.add(pointCloud);

    const lineGeometry = new THREE.BufferGeometry();
    lineGeometry.setAttribute("position", new THREE.BufferAttribute(nearestNeighborSegments(points, NEIGHBOR_K), 3));
    const lineMaterial = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.15 });
    const lines = new THREE.LineSegments(lineGeometry, lineMaterial);
    group.add(lines);

    let frameId;
    const animate = () => {
      const pct = breadthRef.current ?? 50;
      const hue = 355 + ((155 - 355 + 360) % 360) * (pct / 100); // sweeps red(355)->green(155) the short way as breadth rises
      const color = new THREE.Color(`hsl(${hue % 360}, ${pct >= 40 && pct <= 60 ? 20 : 80}%, ${pct >= 40 && pct <= 60 ? 70 : 58}%)`);
      pointsMaterial.color = color;
      lineMaterial.color = color;

      const speed = BASE_ANGULAR_VELOCITY * (1 + (1 - pct / 100) * 2);
      group.rotation.y += speed;
      group.rotation.x += speed * 0.3;

      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      animate();
    } else {
      renderer.render(scene, camera);
    }

    const onResize = () => {
      const w = container.clientWidth || 400, h = container.clientHeight || 400;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", onResize);
      pointsGeometry.dispose();
      pointsMaterial.dispose();
      lineGeometry.dispose();
      lineMaterial.dispose();
      renderer.dispose();
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={containerRef} className={className} data-testid="market-core" />;
}
