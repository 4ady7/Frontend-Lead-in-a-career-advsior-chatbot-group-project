// CareerPath — career chatbot I built for my uni project
// started this after asking students about their need for a career chatbot, and after viewing their results I said why not make it a chat thing, why not make it a thing
// probably overcomplicated it but whatever, it works

// main logic for the chat
// built this step by step rather than plannin everything out first
// maybe not the cleanest structure, but easier to manage while building

let threadId = null;

// keeping everythin in one object for now — but could split this out later
const sessionData = {
  degree: '',
  interests: '',
  chatHistory: [], // not actually using this for anything yet but might do later
  interviewPractice: {
  active: false,
  awaitingRole: false,
  question: '',
  questionIndex: 0,
  totalQuestions: 0,
  targetRole: ''
}
};

//privacy consent box checker 
function updateBtn() {
  const consentCheckbox = document.getElementById("privacy-consent");
  const startButton = document.getElementById("start-btn");
  const warning = document.getElementById("consent-warning");


  if (!consentCheckbox || !startButton) return;

  if (consentCheckbox.checked) {
    startButton.disabled = false;

    if (warning) {
      warning.style.display = "none";
    }
  } else {
    startButton.disabled = true;
  }
}

// maps reply length to a typing delay so responses don't just pop in instantly
// felt weird without this — like it was too fast to feel real
// could use a fixed delay but this feels a bit more natural
function getTypingDelay(text) {
  const wordCount = text.split(' ').length;
  if (wordCount < 20) return 500 + Math.random() * 200; //if the les than 20 words, then creating delayed wait time btw 500 and 700 miliseconds
  if (wordCount < 60) return 700 + Math.random() * 400; //if the les than 60 words, then creating delayed wait time btw 700 and 1100 miliseconds
  return 900 + Math.random() * 500; //and for long messages giving a bit more breathing room, so they will have a delayed wait time btw 900 and 1400 miliseconds
}

function beginChat() {
const consentCheckbox = document.getElementById("privacy-consent");
const warning = document.getElementById("consent-warning");

if (!consentCheckbox || !consentCheckbox.checked) {
  if (warning) {
    warning.style.display = "block";
  }
  return;
}
  const degreeBox = document.getElementById('degree');
  const interestBox = document.getElementById('interests');

  sessionData.degree = degreeBox.value.trim();
  sessionData.interests = interestBox.value.trim();

  threadId = 'session-' + Date.now();

  // just hiding/showing — not doing any routing between pages
  // thought about hash-based routing but decided not to go for since I am only aiming to create two screen pages and not more
  document.getElementById('home').style.display = 'none';
  document.getElementById('chat').style.display = 'flex';

  const greeting = buildGreeting(sessionData.degree, sessionData.interests);
  addBotMessage(greeting.text, greeting.suggestions);

  if (sessionData.degree || sessionData.interests) {
    const contextMessage = buildContextMessage(sessionData.degree, sessionData.interests);
    fetch('http://127.0.0.1:8000/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_text: contextMessage,
        thread_id: threadId
      })
    }).catch(() => {});
  }
}

function buildContextMessage(degree, interests) {
  let msg = 'Context about me: ';
  if (degree) msg += `I am studying ${degree}. `;
  if (interests) msg += `I am interested in ${interests}. `;
  msg += 'Please keep this in mind for the rest of our conversation.';
  return msg;
}

function goHome() {
  // Go back to the landing page
  document.getElementById("chat").style.display = "none";
  document.getElementById("home").style.display = "block";
  document.getElementById('messages').innerHTML = '';
  document.getElementById('chat-input').value = '';
  document.getElementById('degree').value = '';
  document.getElementById('interests').value = '';
  document.getElementById('privacy-consent').checked = false;
  document.getElementById('start-btn').disabled = true;

  // Clear the chat messages
  const messages = document.getElementById("messages");
  if (messages) {
    messages.innerHTML = "";
  }

  // Clear chat input
  const msgInput = document.getElementById("chat-input");
  if (msgInput) {
    msgInput.value = "";
  }

  // Clear uploaded CV input
  const cvUpload = document.getElementById("cv-upload");
  if (cvUpload) {
    cvUpload.value = "";
  }

  // Clear landing page inputs
  const degreeBox = document.getElementById("degree");
  if (degreeBox) {
    degreeBox.value = "";
  }

  const interestBox = document.getElementById("interests");
  if (interestBox) {
    interestBox.value = "";
  }

  // Reset privacy consent
  const consentBox = document.getElementById("privacy-consent");
  if (consentBox) {
    consentBox.checked = false;
  }

  // Disable start button again until consent is ticked
  const startBtn = document.getElementById("start-btn");
  if (startBtn) {
    startBtn.disabled = true;
  }

  // Hide consent warning if it was showing
  const consentWarning = document.getElementById("consent-warning");
  if (consentWarning) {
    consentWarning.style.display = "none";
  }

  // Start a fresh backend conversation next time
  threadId = "student-" + Date.now();

  // Reset interview practice if your app uses these variables
  interviewMode = false;
  currentInterviewQuestion = "";
  currentInterviewIndex = 0;
}


function enterSend(e) {
  //only handling enter, shift+enter for newlines would need a textarea — revisit if time allows
  if (e.key === 'Enter') sendMsg();
};


// this function handles input, triggers typing, manages delay so i could rethink about splitting into handleSend() and displayReply() but keeping it together for now
async function sendMsg() {
  const inputBox = document.getElementById('chat-input');

  let msg = inputBox.value;

  //had an issue where empty messages were getting sent when accidently clicking on Enter, so now i am checking if the user is not sending an empty message
  if (msg === '' || msg.trim() === '') {
    return;
  }

  const msgText = msg.trim();

  addUserMessage(msgText);
  inputBox.value = ''; //automatically removing the text from user input box, to prevent having to manually delete the message that the user writes after each time the send button is used

  if (sessionData.interviewPractice.awaitingRole) {
    await beginInterviewWithRole(msgText);
    return;
  }

  if (sessionData.interviewPractice.active) {
    await sendInterviewAnswer(msgText);
    return;
  }


  // show the typing indicator while we "process" the reply, which feels a lot more natural than the message just appearing
  const typingBubble = typingDots();
  
  const delay = getTypingDelay(msgText);

  try {
    const response = await fetch('http://127.0.0.1:8000/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_text: msgText,
        thread_id: threadId,
        degree: sessionData.degree,
        interests: sessionData.interests 
      })
    });

    const data = await response.json();
    typingBubble.remove();
    addBotMessage(data.answer, null); // backend doesn't send suggestions yet

  } catch (error) {
    typingBubble.remove();
    addBotMessage('Something went wrong. Please try again.', null);
  }
}


function quickSend (text) {
document.getElementById('chat-input').value = text;
sendMsg();//calling the sendMsg function
}

// interview simulation
function interviewMode() {
  if (!threadId) {
    threadId = 'session-' + Date.now();
  }

  sessionData.interviewPractice.active = false;
  sessionData.interviewPractice.awaitingRole = true;
  sessionData.interviewPractice.question = '';
  sessionData.interviewPractice.questionIndex = 0;
  sessionData.interviewPractice.totalQuestions = 0;
  sessionData.interviewPractice.targetRole = '';

  addUserMessage('Start interview practice');
  addBotMessage(
    'Great — what role are you practising for? For example: software developer internship, marketing assistant, graduate scheme, data analyst placement.',
    ['Internship', 'Placement', 'Graduate scheme']
  );

  const input = document.getElementById('chat-input');
  if (input) {
    input.placeholder = 'Type the role you are practising for...';
  }
}

async function beginInterviewWithRole(targetRole) {
  sessionData.interviewPractice.targetRole = targetRole.trim();
  sessionData.interviewPractice.awaitingRole = false;
  sessionData.interviewPractice.active = true;

  const typingBubble = typingDots();

  try {
    const response = await fetch('http://127.0.0.1:8000/interview/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: threadId,
        degree: sessionData.degree,
        interests: sessionData.interests,
        target_role: sessionData.interviewPractice.targetRole
      })
    });

    const data = await response.json();
    typingBubble.remove();

    sessionData.interviewPractice.question = data.question;
    sessionData.interviewPractice.questionIndex = data.question_index;
    sessionData.interviewPractice.totalQuestions = data.total_questions;
    sessionData.interviewPractice.active = !data.complete;

    addBotMessage(data.message, ['End interview practice']);

    const input = document.getElementById('chat-input');
    if (input) {
      input.placeholder = 'Type your interview answer...';
    }

  } catch (error) {
    typingBubble.remove();
    sessionData.interviewPractice.active = false;
    sessionData.interviewPractice.awaitingRole = false;
    addBotMessage('Something went wrong starting interview practice. Please try again.', null);
  }
}


async function sendInterviewAnswer(answerText) {
  if (answerText.toLowerCase() === 'end interview practice') {
    endInterviewPractice();
    return;
  }

  const typingBubble = typingDots();

  try {
    const response = await fetch('http://127.0.0.1:8000/interview/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: threadId,
        question_index: sessionData.interviewPractice.questionIndex,
        question: sessionData.interviewPractice.question,
        user_answer: answerText,
        degree: sessionData.degree,
        interests: sessionData.interests,
        target_role: sessionData.interviewPractice.targetRole
      })
    });

    const data = await response.json();
    typingBubble.remove();

    sessionData.interviewPractice.question = data.question;
    sessionData.interviewPractice.questionIndex = data.question_index;
    sessionData.interviewPractice.totalQuestions = data.total_questions;
    sessionData.interviewPractice.active = !data.complete;

    if (data.complete) {
      const input = document.getElementById('chat-input');
      if (input) {
        input.placeholder = 'Ask something...';
      }

      addBotMessage(data.message, ['Practise again', 'Help me improve my interview answers']);
    } else {
      addBotMessage(data.message, ['End interview practice']);
    }

  } catch (error) {
    typingBubble.remove();
    addBotMessage('Something went wrong scoring your answer. Please try again.', null);
  }
}

function endInterviewPractice() {
  sessionData.interviewPractice.active = false;
  sessionData.interviewPractice.awaitingRole = false;
  sessionData.interviewPractice.question = '';
  sessionData.interviewPractice.questionIndex = 0;
  sessionData.interviewPractice.totalQuestions = 0;

  const input = document.getElementById('chat-input');
  if (input) {
    input.placeholder = 'Ask something...';
  }

  addBotMessage('Interview practice ended. You can restart it from the sidebar anytime.', null);
}

// handles CV file upload — reads the file and sends its contents as context to the bot
// only handles text-based files for now (.txt) — PDF/Word would need a backend parser
// for now, if it's not readable as text, it just sends the filename so the bot knows a CV was shared
function readCV(event) {
  const file = event.target.files[0]; // grab the first file the user selected
  if (!file) return; // if no file was selected, stop here and do nothing

  event.target.value = ''; // reset the file input so the same file can be uploaded again later if needed

  const reader = new FileReader(); // create a FileReader object to read the file's contents

  reader.onload = function(e) { // this runs automatically once the file has finished loading
    const cvText = e.target.result; // the full text content of the file is now stored here

    const message = `I've uploaded my CV. Here's the content:\n\n${cvText}\n\nCan you review it and give me feedback?`; // build the mesage to send to the bot, with the CV text embedded inside it

    addUserMessage(`CV uploaded: ${file.name}`); // showw a message in the chat so the user knows their file was picked up

    const typingBubble = typingDots(); // show the animated typin dots while waiting for the bot's response

    fetch('http://127.0.0.1:8000/chat', { // send a POST request to the backend with the CV content
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }, // tell the server we're sendin JSON
      body: JSON.stringify({
        user_text: message, // the CV content wrapped in a prompt asking for feedback
        thread_id: threadId, // the current session ID so the backend keeps context
        degree: sessionData.degree, // pass the user's degree for personalised feedback
        interests: sessionData.interests // pass the user's interests also for personalised feedback
      })
    })
    .then(r => r.json()) // parse the response from the server as JSON
    .then(data => {
      typingBubble.remove(); // removee the typing indicator now that the reply has arrived
      addBotMessage(data.answer, null); // displays the bot's CV feedback in the chat
    })
    .catch(() => {
      typingBubble.remove(); // remove the typing indicator even if something went wrong
      addBotMessage('Something went wrong reading your CV. Please try again.', null); // show a fallback error mesage to the user
    });
  };

  reader.onerror = function() { // this runs if the FileReader itself fails to read the file
    addBotMessage("Couldn't read that file — try saving it as a .txt and uploading again.", null); // tell the user to try a different format
  };

  reader.readAsText(file); // start reading the file as plain text — triggers onload when done
}

function addUserMessage(text) {
  const el = document.createElement('div'); //every time the function is called, it creates a new div before putting the text inisde of it, and assigning it to the variable el
  el.className = 'msg user'; //giving the new div a CSS class called msg user
  
  //adding bubble around the user message
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  el.appendChild(bubble);

  const msgs = document.getElementById('messages');
  msgs.appendChild(el); //displaying the user's message
  scrollToBottom(); //calling the function scrollToBottom to scroll to the current chat

  sessionData.chatHistory.push({ role: 'user', text }); // not doing anything with this yet lol
}

function addBotMessage(text, suggestions) {
  const msgDiv = document.createElement('div');
  msgDiv.className = 'msg bot';

  //adding bubble around the bot message
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  msgDiv.appendChild(bubble);

  if (suggestions && suggestions.length) {
    const sugDiv = document.createElement('div');
    sugDiv.className = 'suggestions';
 
    suggestions.forEach(s => {
      const btn = document.createElement('button');
      btn.className = 'sug-btn';
      btn.textContent = s;
      btn.addEventListener('click', async () => {
        if (s === 'End interview practice') {
        endInterviewPractice();
      } else if (s === 'Practise again') {
        interviewMode();
      } else if (sessionData.interviewPractice.awaitingRole) {
        addUserMessage(s);
        await beginInterviewWithRole(s);
      } else {
        quickSend(s);
      }
    });
      sugDiv.appendChild(btn);
    });
 
    msgDiv.appendChild(sugDiv);
  }


  document.getElementById('messages').appendChild(msgDiv);
  scrollToBottom();

  sessionData.chatHistory.push({ role: 'bot', text });
}

//function for the typing indicator during the wait time after the sent user message and before the bot response.
function typingDots() {
  const typingDiv = document.createElement('div');
  typingDiv.className = 'msg bot typing';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('span');
    dot.className = 'dot';
    bubble.appendChild(dot);
  }
  typingDiv.appendChild(bubble);
  document.getElementById('messages').appendChild(typingDiv);
  scrollToBottom();
  return typingDiv; // returns it so the caller can remove it when the real reply comes in
}

// scrollIntoView on the last message would probably be nicer but i tried it and it actuallyy felt weird for a chat, instant is better
function scrollToBottom() {
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

// leaving this here in case I want it later
// function clearChat() {
//   thought about adding a "start over" button at the top
//   but wasn't sure where to put it without cluttering the header
//   document.getElementById('messages').innerHTML = '';
//   sessionData.chatHistory = [];
// }

//also thought about adding a "save conversation" feature using localStorage maybe if I had user accounts at some point
//and though about pinning conversations and could add that later



function buildGreeting(degree, interests) {
  let text = `Hey! `;

  if (degree && interests) {
    text += `So you're studying ${degree} and interested in ${interests}? Good starting point. `;
  } else if (degree) {
    text += `So you're studying ${degree}, how can I help you? `;
  } else if (interests) {
    text += `Interested in ${interests}? Good. Let's start there. `;
  }
  if (!degree && !interests) {
    text += `No idea what direction you're headed? That's fine, we can figure it out. `;
  }

  text += `\n\nWhat do you want to start with?`;

  return { text };
}

function openFeedback() {
  const widget = document.getElementById('feedback-widget');
  widget.classList.toggle('collapsed');
}

async function handleFeedback() {
  const helpfulness = Number(document.getElementById('feedback-helpfulness').value);
  const clarity = Number(document.getElementById('feedback-clarity').value);
  const relevance = Number(document.getElementById('feedback-relevance').value);
  const trust = Number(document.getElementById('feedback-trust').value);
  const comment = document.getElementById('feedback-comment').value.trim();

  if (!helpfulness || !clarity || !relevance || !trust) {
    document.getElementById('feedback-text').textContent =
      "Please fill out all four ratings.";
    return;
  }

  try {
    const response = await fetch('http://127.0.0.1:8000/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: threadId,
        helpfulness: helpfulness,
        clarity: clarity,
        relevance: relevance,
        trust: trust,
        comment: comment
      })
    });

    if (!response.ok) {
      throw new Error('Feedback was not saved');
    }

    document.getElementById('feedback-text').textContent = "Thanks for the feedback!";

    document.getElementById('feedback-helpfulness').value = "";
    document.getElementById('feedback-clarity').value = "";
    document.getElementById('feedback-relevance').value = "";
    document.getElementById('feedback-trust').value = "";
    document.getElementById('feedback-comment').value = "";

    setTimeout(() => {
      hideFeedback();
      feedbackText.textContent = 'Rate the chatbot';
    }, 1000);



  } catch (error) {
    console.error(error);
    document.getElementById('feedback-text').textContent =
      "Could not save feedback. Check the backend.";
  }
}

// feedback
function hideFeedback() {
  const widget = document.getElementById('feedback-widget');
  widget.classList.add('collapsed');

  const feedbackText = document.getElementById('feedback-text');
  feedbackText.textContent = 'Rate the chatbot';
}