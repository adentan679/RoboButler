# Validation report

Integration candidate based on team source commit `5b2ddda989908b18566bfb2381e0f541582ae974`.

**Result: 62 automated tests passed, zero failures, zero skips.** The default subprocess demo also completed successfully in a separate run. All Python files passed syntax compilation. Full captured outputs are in `test-results.txt` and `demo-output.txt`.

Validation environment: Linux x86_64, Python 3.12.14, NumPy 2.3.5, g++ 13.3.0. These are test-environment versions, not a claim that the Pi vision environments were installed or tested. The gesture requirements preserve the team's documented versions, including NumPy 1.26.4.

| Test group | Tests | What was exercised |
|---|---:|---|
| Coordinator and gesture filter | 24 | Full round trip; explicit stopped/stowed gates; fresh target on resume; both release and process exit; target loss; obstacles; wrong tag; stale/duplicate frames; old sessions; busy actuator; all gesture commands; held gestures; missing/wrong completions; Arduino reset; worker crash; invalid commands; shutdown |
| Serial/drive/process adapters | 8 | Partial serial lines, legacy firmware rejection, serial disconnection, port identity constraints, independent drive expiry, drive write failure, real child-process handoff and released camera ownership |
| Actual path controller | 3 | Positive command for valid near endpoints at 1.0/0.6 m; empty/behind path stop; obstacle stop |
| VESC bridge | 9 | Immediate zero-duty packet, negative input behavior, missing port, numbered-port rejection, connection/write failures, cleanup, short writes, nonfinite commands |
| Production vision-worker loops with mock APIs | 3 | Fresh frames once each without browser clients, close/release lifecycle, navigation camera-only mode, camera error cleanup |
| Actual Arduino sketch under native mocks | 1 | Host compilation with warnings treated as errors; handshake; no boot servo movement; servo selection; 300 pulses each way; unverified retraction state; STOP; busy/duplicate-ID rejection; heartbeat timeout; bounded serial input |
| Actual FastSAM thread lifecycle methods with model stub | 1 | Thread shutdown and inference-failure propagation |
| Thumbs-up resume and classifier | 13 | Two-second hold; interruptions and capture gaps; busy/extended/unverified stow rejection; duplicate and pre-confirmation frames; drive fault; typed-resume rejection; synthetic landmark mapping and hold configuration |
| **Total** | **62** | **All passed** |

The process demo uses the actual ProcessWorkers launcher and production coordinator/Arduino parser. Synthetic camera workers run as separate OS processes. A loopback socket represents exclusive OAK-D ownership: a second concurrent owner cannot bind it, and the OS releases ownership even if a simulated process dies. The demo returns to navigation and obtains a fresh nonzero drive request only after its simulated stow confirmation and a two-second thumbs-up. There is no typed-resume call in the demo. Its VESC and Arduino transport are fake.

During validation, a file-based simulated camera marker was found capable of persisting after a prior interrupted run. It was replaced with OS-owned socket lifetime. A subsequent complete test run and separate demo run passed. Production camera ownership is still managed by worker cleanup plus confirmed process exit, not by this simulation socket.

## What the passing tests establish

The exercised mode sequence, command interlocks, serial protocol handling, worker lifecycle and failure responses behave as specified for the tested inputs. Tests execute production coordinator/adapter code. The firmware test includes the actual `.ino`, not a rewrite of its motion logic.

## What remains unverified

- Real OAK-D operation and sequential DepthAI v2/v3 reopen on the Raspberry Pi.
- Dependency installation, native SDK/MediaPipe compatibility and real frame throughput.
- Accuracy of AprilTag pose, hand recognition, ground estimation, obstacle masks and path planning on real images.
- Actual vehicle stopping/holding, VESC controller-side timeout, steering calibration or duty-to-speed behavior.
- Arduino Mega board compilation/upload, electrical timing under interrupts, wiring and USB reset behavior.
- Servo range, real lift position, calibrated travel, limit protection, driver current and payload capacity.

The software therefore supports confidence in the tested coordination logic. It is not a guarantee that the physical robot will work without bench validation. Hardware mode intentionally requires supervised physical confirmations; it does not fabricate sensor feedback.

The thumbs-up classifier tests use synthetic landmarks for both mirrored hands and rejection of sideways/downward thumbs. They do not validate recognition accuracy on real hand images.
