// Twilio Function: <Dial> action callback.
// Fires only when the dial to the cell finished — checks whether it was
// actually answered. If not, texts the caller (fast reassurance) and
// texts the electrician (so he knows to call back and to whom).
//
// This is the "action" URL set on the <Dial> in incoming-call.js —
// Twilio deploys it alongside that function automatically at
// https://<service>.twil.io/call-status

exports.handler = function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  const status = event.DialCallStatus; // completed | no-answer | busy | failed

  if (status === 'completed') {
    callback(null, twiml);
    return;
  }

  const client = context.getTwilioClient();
  const caller = event.From;
  const business = context.BUSINESS_NAME || 'the electrician';

  Promise.all([
    client.messages.create({
      to: caller,
      from: context.TWILIO_NUMBER,
      body:
        `Sorry we missed your call! This is ${business} — we're on a job ` +
        `right now but will call you back shortly. Reply here with what's ` +
        `going on and we'll get right on it.`,
    }),
    client.messages.create({
      to: context.ELECTRICIAN_CELL,
      from: context.TWILIO_NUMBER,
      body: `Missed call from ${caller}. Auto-text sent to them — call back when you can.`,
    }),
  ])
    .then(() => callback(null, twiml))
    .catch((err) => callback(err));
};
