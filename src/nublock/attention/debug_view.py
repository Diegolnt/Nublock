"""Debug view (FR-35, opt-in): ventana en vivo con landmarks y estado. Sin grabación.

Corre en el main thread: en macOS las ventanas de OpenCV (`cv2.imshow`) deben crearse ahí.
"""

import cv2

from nublock.attention.camera import Camera
from nublock.attention.monitor import AttentionPipeline
from nublock.attention.state_machine import AttentionStateMachine
from nublock.attention.states import AttentionState
from nublock.config import AttentionConfig
from nublock.timeutils import utc_now

WINDOW = "Nublock debug view (q o Esc para salir)"
COLORS: dict[AttentionState, tuple[int, int, int]] = {  # BGR
    AttentionState.FOCUSED: (80, 200, 80),
    AttentionState.LOOKING_AWAY: (0, 200, 255),
    AttentionState.LOOKING_DOWN: (0, 160, 255),
    AttentionState.PHONE: (60, 60, 255),
}
WHITE = (255, 255, 255)


def run_debug_view(config: AttentionConfig, camera: Camera, pipeline: AttentionPipeline) -> None:
    machine = AttentionStateMachine(config.state_debounce_seconds)
    min_score = config.phone_detection.min_score
    best_phone_score = 0.0
    if not camera.open():
        raise RuntimeError("No se pudo abrir la cámara (revisa el permiso Camera de tu terminal)")
    try:
        while True:
            frame = camera.read()
            if frame is None:
                break
            now = utc_now()
            observation, raw = pipeline.process(frame, now)
            machine.update(raw, now)
            best_phone_score = max(best_phone_score, pipeline.last_phone_score)

            # Para mostrar usamos una copia reducida del frame (solo en vivo, nunca se guarda).
            full_height, full_width = frame.shape[:2]
            scale = min(1.0, config.frame_width / full_width)
            view = cv2.resize(frame, (round(full_width * scale), round(full_height * scale)))
            height, width = view.shape[:2]
            if pipeline.last_phone_box is not None:
                # Rectángulo donde se busca el teléfono: rojo si lo ve, gris si no.
                x0, y0, x1, y1 = (round(value * scale) for value in pipeline.last_phone_box)
                seen = pipeline.last_phone_score >= min_score
                cv2.rectangle(
                    view, (x0, y0), (x1, y1), (60, 60, 255) if seen else (150, 150, 150), 2
                )
            if observation is not None:
                for x, y in observation.landmarks[::4]:  # 1 de cada 4 de los 478 puntos
                    cv2.circle(view, (int(x * width), int(y * height)), 1, WHITE, -1)
                info = (
                    f"yaw {observation.yaw:+.1f}  pitch {observation.pitch:+.1f}  "
                    f"gaze_down {observation.gaze_down:.2f}"
                )
                cv2.putText(view, info, (10, height - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            phone = f"phone {pipeline.last_phone_score:.2f} (umbral {min_score:.2f})"
            cv2.putText(view, phone, (10, height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            state = machine.state or raw
            color = COLORS.get(state, (160, 160, 160))
            label = f"{state}  (raw: {raw})"
            cv2.putText(view, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.imshow(WINDOW, view)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        camera.release()
        pipeline.close()
        cv2.destroyAllWindows()
    print(
        f"Score máximo de teléfono en esta sesión: {best_phone_score:.2f} (umbral {min_score:.2f})"
    )
