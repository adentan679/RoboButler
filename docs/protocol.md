# Host/Arduino protocol and ownership

The supervisor owns the Arduino port throughout both modes. Camera workers never write USB serial. The VESC has its own sole writer thread; no other process should run a standalone VESC program concurrently.

Arduino baud: 9600. Lines are ASCII and newline-terminated. Firmware input is bounded to 63 characters. Motion uses a nonblocking loop so PING and STOP can be handled during movement.

| Host message | Arduino response / behavior |
|---|---|
| `HELLO` | `READY ROBOBUTLER1`; establishes heartbeat link |
| `PING` | `PONG`; host sends every 0.5 s |
| `1 STOW` | `ACK 1`, `DONE 1 STOWED`; operator confirmation, no motor movement |
| `2 Command_1` | `ACK 2`; rotate then extend; `DONE 2 EXTENDED` after pulse generation |
| `3 RETURN` | `ACK 3`; retract; `DONE 3 RETRACTED_UNVERIFIED` |
| `STOP` | Stop step pulses, invalidate position; `FAULT STOPPED` |

Use increasing positive command IDs; do not reuse or blindly retry a motion after losing its reply. There is only one pending command. STOW is permitted at boot/unknown or after retraction, not while extended or moving. A selection requires STOWED. RETURN requires EXTENDED. ACK means accepted, DONE means software action finished. Neither message is a position measurement.

Firmware emits `BOOT ROBOBUTLER1` at startup. Receiving BOOT after the host handshake faults the session and invalidates position. Lack of host heartbeat for over two seconds also stops firmware motion and invalidates position. The firmware has no home sensor; automatic position recovery is intentionally absent.

Camera workers send JSON lines with an integer session token and event type. Observation messages include a strictly increasing frame sequence and a host monotonic capture timestamp. Old sessions and repeated frames cannot authorize a new action. READY confirms worker initialization; RELEASED is emitted only after camera cleanup. The parent also requires successful process exit before starting the next owner. Release failure/timeout never permits concurrent camera startup.

The same coordinator consumes simulated and real worker messages. Tests use synthetic detections to validate coordination, not to estimate real-world computer-vision accuracy.

Resume uses a `THUMBS_UP` vision label held for two seconds on fresh frames after acknowledged physical stow. It is handled entirely by the coordinator and is never sent to the Arduino. The terminal `resume` action has been removed. Retraction completion alone still cannot authorize resumption.
