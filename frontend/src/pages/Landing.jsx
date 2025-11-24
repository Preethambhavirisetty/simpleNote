import { useNavigate } from 'react-router-dom';

export default function Landing() {
  const navigate = useNavigate();

  const features = [
    {
      icon: '📝',
      title: 'Rich Text Editor',
      description: 'Format text with bold, italic, lists, colors, and more'
    },
    {
      icon: '🌙',
      title: 'Dark Mode',
      description: 'Beautiful dark and light themes'
    },
    {
      icon: '📤',
      title: 'Import Files',
      description: 'Upload .docx and .txt files'
    },
    {
      icon: '📥',
      title: 'Export PDF',
      description: 'Download notes as PDFs'
    },
    {
      icon: '🖼️',
      title: 'Media Support',
      description: 'Add images and videos'
    },
    {
      icon: '📊',
      title: 'Tables',
      description: 'Create formatted tables'
    },
    {
      icon: '💾',
      title: 'Auto-save',
      description: 'Never lose your work'
    },
    {
      icon: '🎨',
      title: 'Color Palette',
      description: 'Highlight with custom colors'
    }
  ];

  return (
    <div className="min-h-screen bg-white text-gray-900">
      {/* Header */}
      <header className="border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div className="flex items-center space-x-2">
              <span className="text-2xl">📝</span>
              <h1 className="text-2xl font-bold">SimpleNote</h1>
            </div>
            <div className="flex gap-4">
              <button
                onClick={() => navigate('/login')}
                className="px-6 py-2 border border-gray-900 hover:bg-gray-100 transition-colors"
              >
                Login
              </button>
              <button
                onClick={() => navigate('/register')}
                className="px-6 py-2 bg-gray-900 text-white hover:bg-gray-800 transition-colors"
              >
                Sign Up
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="py-20 border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-5xl font-bold mb-6">
            Your Notes, Simplified.
          </h2>
          <p className="text-xl text-gray-600 mb-10 max-w-2xl mx-auto">
            A modern note-taking application with powerful features.
            Simple, fast, and reliable.
          </p>
          <button
            onClick={() => navigate('/register')}
            className="px-8 py-4 bg-gray-900 text-white text-lg hover:bg-gray-800 transition-colors"
          >
            Get Started Free
          </button>
        </div>
      </section>

      {/* Features Grid */}
      <section className="py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h3 className="text-3xl font-bold text-center mb-12">
            Everything You Need
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            {features.map((feature, index) => (
              <div
                key={index}
                className="p-6 border border-gray-200 hover:border-gray-900 transition-all"
              >
                <div className="text-4xl mb-4">{feature.icon}</div>
                <h4 className="text-xl font-bold mb-2">{feature.title}</h4>
                <p className="text-gray-600">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 bg-gray-900 text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h3 className="text-4xl font-bold mb-6">
            Ready to Get Started?
          </h3>
          <p className="text-xl text-gray-300 mb-10">
            Join SimpleNote today and experience modern note-taking.
          </p>
          <button
            onClick={() => navigate('/register')}
            className="px-8 py-4 bg-white text-gray-900 text-lg hover:bg-gray-100 transition-colors"
          >
            Create Free Account
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-200 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-gray-600">
          <p>&copy; 2025 SimpleNote. Built with ❤️ for productivity.</p>
        </div>
      </footer>
    </div>
  );
}

