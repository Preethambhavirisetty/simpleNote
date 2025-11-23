export const templates = {
  blank: {
    name: 'Blank Page',
    content: ''
  },
  lined: {
    name: 'Lined Paper',
    content: '<p><br></p>'.repeat(20)
  },
  meeting: {
    name: 'Meeting Notes',
    content: `
      <h2>Meeting Notes</h2>
      <p><strong>Date:</strong> ${new Date().toLocaleDateString()}</p>
      <p><strong>Attendees:</strong> </p>
      <p><strong>Agenda:</strong></p>
      <ul><li></li></ul>
      <p><strong>Action Items:</strong></p>
      <ul><li></li></ul>
      <p><strong>Next Meeting:</strong> </p>
    `
  },
  todo: {
    name: 'To-Do List',
    content: `
      <h2>To-Do List</h2>
      <p><strong>Date:</strong> ${new Date().toLocaleDateString()}</p>
      <ul>
        <li>☐ Task 1</li>
        <li>☐ Task 2</li>
        <li>☐ Task 3</li>
      </ul>
    `
  },
  journal: {
    name: 'Daily Journal',
    content: `
      <h2>Daily Journal</h2>
      <p><strong>Date:</strong> ${new Date().toLocaleDateString()}</p>
      <p><strong>Mood:</strong> </p>
      <p><strong>Today I:</strong></p>
      <p></p>
      <p><strong>Grateful for:</strong></p>
      <p></p>
      <p><strong>Tomorrow's Goals:</strong></p>
      <p></p>
    `
  },
  project: {
    name: 'Project Plan',
    content: `
      <h2>Project Plan</h2>
      <p><strong>Project Name:</strong> </p>
      <p><strong>Start Date:</strong> ${new Date().toLocaleDateString()}</p>
      <p><strong>Objectives:</strong></p>
      <ul><li></li></ul>
      <p><strong>Milestones:</strong></p>
      <ul><li></li></ul>
      <p><strong>Resources:</strong></p>
      <ul><li></li></ul>
    `
  }
};

