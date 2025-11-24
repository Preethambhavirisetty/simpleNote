import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function Landing() {
  const navigate = useNavigate();
  const [activeFeature, setActiveFeature] = useState(null);

  const features = [
    {
      title: 'Rich Text Editor',
      description: 'Format text with bold, italic, headings, lists, and more',
      icon: '📝'
    },
    {
      title: 'Dark Mode',
      description: 'Beautiful dark and light themes for comfortable writing',
      icon: '🌙'
    },
    {
      title: 'File Import',
      description: 'Upload .docx and .txt files directly',
      icon: '📤'
    },
    {
      title: 'PDF Export',
      description: 'Download your notes as professional PDFs',
      icon: '📥'
    },
    {
      title: 'Media Support',
      description: 'Embed images and videos in your documents',
      icon: '🖼️'
    },
    {
      title: 'Tables',
      description: 'Create and manage tables with ease',
      icon: '📊'
    },
    {
      title: 'Auto-save',
      description: 'Never lose your work with automatic saving',
      icon: '💾'
    },
    {
      title: 'Color Palette',
      description: 'Highlight text with custom colors',
      icon: '🎨'
    },
    {
      title: 'Links',
      description: 'Create hyperlinks to external resources',
      icon: '🔗'
    },
    {
      title: 'Clear Formatting',
      description: 'Remove all formatting with one click',
      icon: '🧹'
    },
    {
      title: 'Sub-lists',
      description: 'Create nested lists with tab indentation',
      icon: '📋'
    },
    {
      title: 'AI Ready',
      description: 'Prepared for AI-powered features',
      icon: '🤖'
    }
  ];

  return (
    <div className="min-h-screen bg-white text-black">
      {/* Header */}
      <header className="border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4 sm:py-6">
            <div className="flex items-center space-x-2">
              <span className="text-xl sm:text-2xl">📝</span>
              <h1 className="text-xl sm:text-2xl font-bold">SimpleNote</h1>
            </div>
            <div className="flex gap-2 sm:gap-4">
              <button
                onClick={() => navigate('/login')}
                className="px-3 sm:px-6 py-2 text-sm sm:text-base border border-black hover:bg-black hover:text-white transition-colors"
              >
                Login
              </button>
              <button
                onClick={() => navigate('/register')}
                className="px-3 sm:px-6 py-2 text-sm sm:text-base bg-black text-white hover:bg-gray-800 transition-colors"
              >
                Sign Up
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="py-12 sm:py-16 md:py-20 border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold mb-4 sm:mb-6">
            Your Notes,<br />Simplified.
          </h2>
          <p className="text-base sm:text-lg md:text-xl text-gray-600 mb-8 sm:mb-10 max-w-2xl mx-auto px-4">
            A modern note-taking application with powerful features.
            Simple, fast, and reliable.
          </p>
          <button
            onClick={() => navigate('/register')}
            className="px-6 sm:px-8 py-3 sm:py-4 bg-black text-white text-base sm:text-lg hover:bg-gray-800 transition-colors"
          >
            Get Started Free
          </button>
        </div>
      </section>

      {/* Features Grid */}
      <section className="py-12 sm:py-16 md:py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h3 className="text-2xl sm:text-3xl font-bold text-center mb-8 sm:mb-12">
            Everything You Need
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6 md:gap-8">
            {features.map((feature, index) => (
              <div
                key={index}
                className={`p-4 sm:p-6 border border-gray-200 hover:border-black transition-all cursor-pointer ${
                  activeFeature === index ? 'bg-black text-white' : 'bg-white'
                }`}
                onMouseEnter={() => setActiveFeature(index)}
                onMouseLeave={() => setActiveFeature(null)}
                onClick={() => setActiveFeature(activeFeature === index ? null : index)}
              >
                <div className="text-3xl sm:text-4xl mb-3 sm:mb-4">{feature.icon}</div>
                <h4 className="text-lg sm:text-xl font-bold mb-2">{feature.title}</h4>
                <p className={`text-sm sm:text-base ${activeFeature === index ? 'text-gray-200' : 'text-gray-600'}`}>
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Stats Section */}
      <section className="py-12 sm:py-16 md:py-20 bg-black text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-8 sm:gap-12 text-center">
            <div>
              <div className="text-3xl sm:text-4xl md:text-5xl font-bold mb-2">Fast</div>
              <p className="text-sm sm:text-base text-gray-400">Lightning quick performance</p>
            </div>
            <div>
              <div className="text-3xl sm:text-4xl md:text-5xl font-bold mb-2">Secure</div>
              <p className="text-sm sm:text-base text-gray-400">Your data is protected</p>
            </div>
            <div>
              <div className="text-3xl sm:text-4xl md:text-5xl font-bold mb-2">Simple</div>
              <p className="text-sm sm:text-base text-gray-400">Intuitive interface</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 border-t border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h3 className="text-4xl font-bold mb-6">
            Ready to Get Started?
          </h3>
          <p className="text-xl text-gray-600 mb-10">
            Join SimpleNote today and experience modern note-taking.
          </p>
          <button
            onClick={() => navigate('/register')}
            className="px-8 py-4 bg-black text-white text-lg hover:bg-gray-800 transition-colors"
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

