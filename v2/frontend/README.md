npm create vite@latest frontend -- --template react
cd frontend

npm install -D tailwindcss@3 postcss autoprefixer
npx tailwindcss init -p

lsof -ti :8081 | xargs kill -9
./build/inference_api

```
src/
├── api/
│   ├── client.js          axios → BE (localhost:3001, withCredentials)
│   ├── agentClient.js     axios → Agent (localhost:3002, X-API-Key header)
│   ├── auth.js            login · register · logout · changePassword
│   ├── users.js           getMe · updateMe · admin CRUD
│   ├── folders.js         list · create · get · update · delete
│   ├── notes.js           list · create · get · update · move · delete · tags
│   ├── tags.js            list · create · get · update · delete
│   └── agent.js           chat · getContext · ingest · streamChatCompletions()
├── stores/
│   ├── authStore.js       user · init (cookie restore) · login · register · logout
│   ├── folderStore.js     folders · CRUD actions
│   ├── noteStore.js       notes · activeNote · CRUD · textToTipTap / tipTapToText
│   ├── tagStore.js        tags · CRUD actions
│   └── chatStore.js       messages · RAG mode · streaming mode
├── components/
│   ├── ProtectedRoute.jsx redirect to /login if no session
│   └── Sidebar.jsx        nav · folders list · inline new-folder input · signout
├── pages/
│   ├── auth/
│   │   ├── LoginPage.jsx
│   │   └── RegisterPage.jsx
│   ├── AppLayout.jsx      sidebar + <Outlet />; fetches folders & tags on mount
│   ├── NotesPage.jsx      split: note list | textarea editor with 1.2s autosave
│   └── ChatPage.jsx       RAG / Stream toggle · SSE streaming · typing indicator
└── App.jsx                createBrowserRouter · session init · 401 broadcast handler
```

1. Login error
2. home page didn't load and threw an error
3. folder created but not handled on the UI properly
4. BE response wrapped with specific format, fix: unwrapped in app.js
5. used wrong field name, content_json vs content, fix: note.content ?? note.content_json
6. FE and BE integrated all ops worked, tested chat with a complex reasoning story, it failed 
    - because its a small model and multi-step lateral thinking are hard for it
    - system prompt is also simplified, "answer from the context provided" structured format isn't enforced
    - Fix: use a 70B+ model
7. test 1, avg performance
    - my model is great at reading, decent at inferring, but struggles with conflicting constraints.
    - prompt tuning missed
8. test 2: prompt tuned
    - 



### Observations:

content:
The Case of the Damp Study
The Setup:
Midway through a dry, scorching desert summer, Sir Reginald was found dead in his study. The room was perfectly sealed: the only door was bolted from the inside, and the single window was locked and barred.
When the police broke in, they found:
Reginald slumped over his desk, dead from a single gunshot wound.
A puddle of water on the floor directly beneath a small, empty birdcage hanging from the ceiling.
A suicide note on the desk, bone dry.
A high-powered space heater turned on "High" in the corner.
No weapon anywhere in the room.
The Twist:
The detective took one look at the puddle and the heater and knew it wasn't suicide—it was murder.
The Question for the LLM:
How was Reginald killed, and where did the weapon go?

Context retrieved from qdrant:
The Case of the Damp Study The Setup: Midway through a dry, scorching desert summer, Sir Reginald was found dead in his study. The room was perfectly sealed: the only door was bolted from the inside, and the single window was locked and barred. When the police broke in, they found: Reginald slumped over his desk, dead from a single gunshot wound. A puddle of water on the floor directly beneath a small, empty birdcage hanging from the ceiling. A\n\nNo weapon anywhere in the room. The Twist: The detective took one look at the puddle and the heater and knew it wasn't suicide—it was murder.\n\nn the floor directly beneath a small, empty birdcage hanging from the ceiling. A suicide note on the desk, bone dry. A high-powered space heater turned on 'High' in the corner."


LLM response:
"Based on the context, it appears that Reginald was killed by a gunshot wound, but there is no physical evidence of a weapon in the room. The detective's conclusion that it was murder suggests that the killer must have taken the weapon with them.\n\nConsidering the presence of a high-powered space heater and a puddle of water directly beneath the birdcage, it's possible that the killer used the heater to create a makeshift projectile, such as a hot metal fragment or a bullet. The birdcage, which is empty, might have been used to deflect or disperse the projectile, making it difficult to find.\n\nIn this scenario, the killer might have used the space heater to fire a bullet or a hot metal fragment at Reginald, who was then killed instantly. The killer would have had to be careful not to leave any physical evidence of the weapon, which is why it's not found in the room."

# ************** completed:failed 70B+ models required ***************


story 1:
Last Tuesday, the team at EcoTech Solutions officially transitioned to a 'Deep Work' schedule. Under this new protocol, all internal meetings are banned between 9:00 AM and 1:00 PM. Employees are required to use the FocusFlow desktop application to track their deep work blocks. The policy states that if an emergency arises, staff must contact their supervisor via Telegram, rather than the standard Slack channels. To celebrate the launch, the CEO, Sarah, ordered 40 pepperoni pizzas and 15 vegan salads from Tony’s Pizzeria for the 1:30 PM debrief.

Question:
What specific app must employees use for tracking, and how should they communicate during an emergency according to this new policy?

NEW Response:
"Evidence:\n- Employees are required to use the FocusFlow desktop application to track their deep work blocks.\n- The policy states that if an emergency arises, staff must contact their supervisor via Telegram, rather than the standard Slack channels.\n\nReasoning:\n1. The policy specifically states that employees must use the FocusFlow desktop application to track their deep work blocks.\n2. The policy also states that in the event of an emergency, staff should contact their supervisor via Telegram, not Slack.\n\nAnswer:\nEmployees must use the FocusFlow desktop application to track their deep work blocks, and in case of an emergency, they should contact their supervisor via Telegram."


Story 2:
Marcus was halfway through his solo hike in the Andes when he realized his primary water filtration straw was missing. He checked his map; the nearest clean spring was a six-hour trek north. However, he was currently standing next to a murky, stagnant pond. In his bag, he had a metal camping cup, a small bundle of dry kindling, a flint-and-steel kit, and a heavy wool blanket. The sun was beginning to set, and the temperature was dropping rapidly. He knew that drinking the pond water directly would cause severe illness, but he also knew he couldn't survive six hours of trekking while severely dehydrated in the freezing night.

Question:
Given the items in his bag, what is Marcus's best course of action to safely stay hydrated before moving north?


New Response:
"Evidence:\n- Marcus is missing his primary water filtration straw.\n- The nearest clean spring is a six-hour trek north.\n- Marcus is standing next to a murky, stagnant pond.\n- He has a metal camping cup, a small bundle of dry kindling, a flint-and-steel kit, and a heavy wool blanket in his bag.\n- Drinking the pond water directly would cause severe illness.\n- Marcus can't survive six hours of trekking while severely dehydrated in the freezing night.\n\nReasoning:\nMarcus needs to find a way to make the pond water safe to drink. He has a flint-and-steel kit, which can be used to create a fire. He also has dry kindling, which can be used as fuel for the fire. He can use the fire to boil the pond water, making it safe to drink. This is his best course of action to safely stay hydrated before moving north.\n\nAnswer:\nMarcus's best course of action is to use the flint-and-steel kit to create a fire, boil the pond water, and then drink it to stay hydrated before moving north."


Story 3: Synthesis & Conflict
Our blog's 'Safety First' guide strictly mandates that 'No chemical accelerants, including gasoline or lighter fluid, should ever be used to start a backyard bonfire.' A separate article on 'Winter Survival' notes that 'In extreme sub-zero conditions, traditional friction-based fire starting is often impossible due to moisture and numbing of the hands.' Today, a user writes in: 'I am trapped in a blizzard in my backyard. My hands are frozen, and I cannot strike a match. I have a bottle of lighter fluid and a pile of damp wood. If I don't start a fire now, I will get hypothermia. What should I do?

Question:
Synthesize the advice from both blog articles. Should the user use the lighter fluid? Explain why based strictly on the blog's provided rules.

New Response:
"Evidence:\n- Our blog's 'Safety First' guide strictly mandates that 'No chemical accelerants, including gasoline or lighter fluid, should ever be used to start a backyard bonfire.'\n- A separate article on 'Winter Survival' notes that 'In extreme sub-zero conditions, traditional friction-based fire starting is often impossible due to moisture and numbing of the hands.'\n- The user is trapped in a blizzard, has frozen hands, and cannot strike a match.\n- The user has a bottle of lighter fluid and a pile of damp wood.\n\nReasoning:\nThe 'Safety First' guide explicitly prohibits the use of chemical accelerants, including lighter fluid, for starting a bonfire. However, the 'Winter Survival' article notes that traditional friction-based fire starting may be impossible in extreme sub-zero conditions. The user's situation meets this criteria, as they are trapped in a blizzard and have frozen hands. Therefore, the 'Winter Survival' article's guidance takes precedence in this specific situation.\n\nAnswer:\nThe user should not use the lighter fluid, as it is a chemical accelerant prohibited by the 'Safety First' guide."