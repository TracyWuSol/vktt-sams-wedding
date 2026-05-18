/**
 * Solace PubSub+ micro-integration layer.
 *
 * Architecture:
 *   S3 upload  →  publish to wedding/s3/photos/uploaded
 *   Facial recognition complete  →  publish to wedding/recognition/completed
 *   Notification dispatched      →  publish to wedding/notifications/send
 *
 * Any external subscriber (another microservice, Solace Connector, etc.)
 * can hook into these topics without modifying this service.
 */
import solace from 'solclientjs';
import { config } from '../config';
import {
  SolacePhotoUploadedPayload,
  SolaceRecognitionCompletedPayload,
  SolaceNotificationPayload,
  SolaceAlertPayload,
} from '../types';

type AnyPayload =
  | SolacePhotoUploadedPayload
  | SolaceRecognitionCompletedPayload
  | SolaceNotificationPayload
  | SolaceAlertPayload;

let session: solace.Session | null = null;
let connected = false;

/** Initialise the Solace factory once at module load. */
(function initFactory() {
  const factoryProps = new solace.SolclientFactoryProperties();
  factoryProps.profile = solace.SolclientFactoryProfiles.version10;
  solace.SolclientFactory.init(factoryProps);
})();

export async function connectSolace(): Promise<void> {
  return new Promise((resolve, reject) => {
    try {

      session = solace.SolclientFactory.createSession({
        url: config.solace.host,
        vpnName: config.solace.vpnName,
        userName: config.solace.username,
        password: config.solace.password,
        connectRetries: 3,
        reconnectRetries: 5,
      });

      session.on(solace.SessionEventCode.UP_NOTICE, () => {
        console.log('[Solace] Connected to broker');
        connected = true;
        resolve();
      });

      session.on(solace.SessionEventCode.CONNECT_FAILED_ERROR, (evt: solace.SessionEvent) => {
        console.error('[Solace] Connection failed:', evt.infoStr);
        connected = false;
        reject(new Error(`Solace connection failed: ${evt.infoStr}`));
      });

      session.on(solace.SessionEventCode.DISCONNECTED, () => {
        console.warn('[Solace] Disconnected from broker');
        connected = false;
      });

      session.connect();
    } catch (err) {
      console.error('[Solace] Failed to create session:', err);
      // Non-fatal — app continues without Solace if broker is unavailable
      resolve();
    }
  });
}

/**
 * Publish a message to a Solace topic.
 * Falls back to a console log if the session is not yet connected so that
 * local development without a broker still works.
 */
export function publish(topic: string, payload: AnyPayload): void {
  const json = JSON.stringify(payload);

  if (!session || !connected) {
    // Graceful degradation: log the event locally
    console.log(`[Solace][OFFLINE] Topic: ${topic} | Payload: ${json}`);
    return;
  }

  try {
    const message = solace.SolclientFactory.createMessage();
    message.setDestination(
      solace.SolclientFactory.createTopicDestination(topic)
    );
    message.setBinaryAttachment(json);
    message.setDeliveryMode(solace.MessageDeliveryModeType.PERSISTENT);
    session.send(message);
    console.log(`[Solace] Published to ${topic}`);
  } catch (err) {
    console.error('[Solace] Publish error:', err);
  }
}

/** Subscribe to a topic and invoke a callback for each received message. */
export function subscribe(
  topic: string,
  handler: (payload: AnyPayload) => void
): void {
  if (!session || !connected) {
    console.warn(`[Solace] Cannot subscribe to ${topic} — not connected`);
    return;
  }

  try {
    session.on(solace.SessionEventCode.MESSAGE, (message: solace.Message) => {
      const dest = message.getDestination();
      if (!dest || dest.getName() !== topic) return;
      const raw = message.getBinaryAttachment();
      if (!raw) return;
      try {
        const parsed = JSON.parse(raw.toString()) as AnyPayload;
        handler(parsed);
      } catch {
        console.error('[Solace] Failed to parse message on', topic);
      }
    });

    session.subscribe(
      solace.SolclientFactory.createTopicDestination(topic),
      true,
      topic,
      10000
    );
    console.log(`[Solace] Subscribed to ${topic}`);
  } catch (err) {
    console.error('[Solace] Subscribe error:', err);
  }
}

export function disconnectSolace(): void {
  if (session && connected) {
    session.disconnect();
  }
}

// Convenience wrappers typed to the specific payload shapes

export function publishPhotoUploaded(payload: SolacePhotoUploadedPayload): void {
  publish(config.solace.topics.photoUploaded, payload);
}

export function publishRecognitionCompleted(payload: SolaceRecognitionCompletedPayload): void {
  publish(config.solace.topics.recognitionCompleted, payload);
}

export function publishNotificationSend(payload: SolaceNotificationPayload): void {
  publish(config.solace.topics.notificationSend, payload);
}

export function publishAlert(
  guestId: string,
  photoId: string,
  payload: SolaceAlertPayload
): void {
  publish(`wedding/alerts/${guestId}/${photoId}`, payload);
}

// Email-channel alert. Consumed by the standalone email-worker via a queue
// subscribed to `wedding/alerts/photos/email/>`.
export function publishEmailAlert(
  guestId: string,
  photoId: string,
  payload: SolaceAlertPayload
): void {
  publish(`wedding/alerts/photos/email/${guestId}/${photoId}`, payload);
}

// Line-channel alert. A separate line-worker (not yet implemented) would
// bind to a queue subscribed to `wedding/alerts/photos/line/>` and dispatch
// the actual Line message via the LINE Messaging API.
export function publishLineAlert(
  guestId: string,
  photoId: string,
  payload: SolaceAlertPayload
): void {
  publish(`wedding/alerts/photos/line/${guestId}/${photoId}`, payload);
}
