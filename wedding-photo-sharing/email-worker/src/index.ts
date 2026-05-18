/**
 * Email worker.
 *
 * Binds to the Solace queue named by `EMAIL_SOLACE_QUEUE`. The queue must be
 * provisioned on the broker with a topic subscription to
 * `wedding/alerts/photos/email/>`. The backend publishes one message per
 * matched guest on `wedding/alerts/photos/email/{guestId}/{photoId}`; this
 * worker consumes them and dispatches the actual SMTP email.
 */
import solace from 'solclientjs';
import { config } from './config';
import { sendEmailFromAlert } from './emailService';
import { EmailAlertPayload } from './types';

(function initFactory() {
  const factoryProps = new solace.SolclientFactoryProperties();
  factoryProps.profile = solace.SolclientFactoryProfiles.version10;
  solace.SolclientFactory.init(factoryProps);
})();

function connectSession(): Promise<solace.Session> {
  return new Promise((resolve, reject) => {
    const session = solace.SolclientFactory.createSession({
      url: config.solace.host,
      vpnName: config.solace.vpnName,
      userName: config.solace.username,
      password: config.solace.password,
      connectRetries: 3,
      reconnectRetries: 5,
    });

    session.on(solace.SessionEventCode.UP_NOTICE, () => {
      console.log('[Solace] Session connected');
      resolve(session);
    });

    session.on(solace.SessionEventCode.CONNECT_FAILED_ERROR, (evt: any) => {
      const info = evt?.infoStr ?? evt?.message ?? String(evt);
      console.error('[Solace] Connect failed:', info);
      reject(new Error(`Solace connect failed: ${info}`));
    });

    session.on(solace.SessionEventCode.DISCONNECTED, () => {
      console.warn('[Solace] Session disconnected');
    });

    session.connect();
  });
}

function startConsumer(session: solace.Session): void {
  const consumer = session.createMessageConsumer({
    queueDescriptor: {
      name: config.solace.queue,
      type: solace.QueueType.QUEUE,
    },
    acknowledgeMode: solace.MessageConsumerAcknowledgeMode.CLIENT,
  });

  consumer.on(solace.MessageConsumerEventName.UP, () => {
    console.log(`[Solace] Bound to queue "${config.solace.queue}"`);
  });

  consumer.on(solace.MessageConsumerEventName.CONNECT_FAILED_ERROR, (evt: any) => {
    const info = evt?.infoStr ?? evt?.message ?? String(evt);
    console.error('[Solace] Consumer bind failed:', info);
  });

  consumer.on(solace.MessageConsumerEventName.DOWN_ERROR, (evt: any) => {
    const info = evt?.infoStr ?? evt?.message ?? String(evt);
    console.error('[Solace] Consumer down:', info);
  });

  consumer.on(solace.MessageConsumerEventName.MESSAGE, async (message) => {
    const topic = message.getDestination()?.getName() ?? '<unknown>';
    const raw = message.getBinaryAttachment();
    if (!raw) {
      console.warn(`[Email] Empty payload on ${topic} — discarding`);
      message.acknowledge();
      return;
    }

    let payload: EmailAlertPayload;
    try {
      payload = JSON.parse(raw.toString()) as EmailAlertPayload;
    } catch (err) {
      console.error(`[Email] Invalid JSON on ${topic} — discarding:`, err);
      message.acknowledge();
      return;
    }

    try {
      await sendEmailFromAlert(payload);
      console.log(
        `[Email] Sent to ${payload.payload?.contactMethod?.value} (topic ${topic})`
      );
      message.acknowledge();
    } catch (err) {
      // Don't ack — Solace will redeliver after the broker's redelivery policy.
      console.error(`[Email] Send failed on ${topic}:`, err);
    }
  });

  consumer.connect();
}

async function main() {
  console.log('[Email Worker] Starting...');
  const session = await connectSession();
  startConsumer(session);

  const shutdown = () => {
    console.log('[Email Worker] Shutting down');
    try {
      session.disconnect();
    } catch {
      // ignore
    }
    process.exit(0);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

main().catch((err) => {
  console.error('[Email Worker] Fatal startup error:', err);
  process.exit(1);
});
