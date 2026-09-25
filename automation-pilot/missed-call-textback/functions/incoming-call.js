// Twilio Function: Voice webhook for the business number.
// Dials the electrician's cell for 20s; on no-answer/busy, call-status.js
// takes over and sends the auto-text.
//
// Set as the "A call comes in" webhook on the Twilio number, method POST.

exports.handler = function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();

  const dial = twiml.dial({
    timeout: 20,
    action: `https://${context.DOMAIN_NAME}/call-status`,
    callerId: context.TWILIO_NUMBER,
  });
  dial.number(context.ELECTRICIAN_CELL);

  callback(null, twiml);
};
